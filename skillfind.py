#!/usr/bin/env python3
"""skillfind - precise lookup over the local Codex skill library.

Why this exists
---------------
Codex injects the name+description of every *enabled* SKILL.md into the model
context on every turn, and that catalog is capped (~82k chars). With a few
hundred skills installed, every description gets truncated and ~20k tokens are
spent per turn on skills that are irrelevant to the current task.

So: keep only a small always-on set enabled, park the rest in skills-off, and
use this tool to find the right few for a task on demand. Parked skills stay
fully readable, so nothing is lost.

Usage
-----
  python skillfind.py --reindex              rebuild the index (after install/removal)
  python skillfind.py "降 aigc 论文"          search, default top 5
  python skillfind.py "fine-tune llm lora" -n 3
  python skillfind.py --list bio-med         list a category
  python skillfind.py --stats                index summary
  python skillfind.py --json "patent claim"  machine-readable output
"""

import argparse
import io
import json
import math
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

CODEX_HOME = os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
ON_DIR = os.path.join(CODEX_HOME, "skills")
OFF_DIR = os.path.join(CODEX_HOME, "skills-off")
INDEX_PATH = os.path.join(CODEX_HOME, "skill-index.json")
PACKS_PATH = os.path.join(CODEX_HOME, "skill-packs.json")

CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+")
WORD = re.compile(r"[a-z0-9][a-z0-9_+.#-]*")

CJK_STOP = set("的了是在和与我你他它这那就都也很会要有个不没把被给对从到为以于其之而且但因所"
               "及等能让使当过又再还只可上下前后里外时")
EN_STOP = {
    "a", "an", "the", "of", "for", "and", "or", "to", "in", "on", "at", "is",
    "are", "be", "with", "my", "this", "that", "it", "its", "use", "using",
    "used", "how", "do", "does", "can", "you", "your", "i", "we",
}
ALIAS_PATH = os.path.join(CODEX_HOME, "skill-aliases.json")


# ---------------------------------------------------------------- tokenizing
def tokenize(text):
    tokens = []
    lowered = text.lower()
    for word in WORD.findall(lowered):
        tokens.append(word)
        if word.endswith("s") and len(word) > 3:
            tokens.append(word[:-1])
    for run in CJK.findall(lowered):
        chars = list(run)
        if len(chars) == 1:
            tokens.append(run)
        for i in range(len(chars) - 1):
            tokens.append(chars[i] + chars[i + 1])
        if len(chars) <= 6:
            tokens.append(run)
    return tokens


# ------------------------------------------------------------------ indexing
def frontmatter(text):
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    return text[3:end] if end > 0 else text[3:4000]


def field(fm, key):
    match = re.search(r"(?m)^%s:\s*(.*)$" % key, fm)
    if not match:
        return ""
    value = match.group(1).strip()
    if value in ("|", ">", "|-", ">-"):
        rest = fm[match.end():].splitlines()
        block = []
        for line in rest:
            if line.strip() and not line.startswith((" ", "\t")):
                break
            block.append(line.strip())
        value = " ".join(part for part in block if part)
    return " ".join(value.split())


def load_packs():
    if not os.path.exists(PACKS_PATH):
        return {}
    data = json.load(io.open(PACKS_PATH, encoding="utf-8"))
    return {k: list(v) for k, v in data.get("packs", {}).items()}


def category_of(packs, name):
    import fnmatch
    for pack, rules in packs.items():
        if pack in ("core", "always-on"):
            continue
        for rule in rules:
            if name == rule or fnmatch.fnmatch(name, rule):
                return pack
    return "other"


def scan(active):
    base = ON_DIR if active else OFF_DIR
    rows = []
    if not os.path.isdir(base):
        return rows
    packs = load_packs()
    for name in sorted(os.listdir(base)):
        path = os.path.join(base, name, "SKILL.md")
        if not os.path.isfile(path):
            continue
        text = io.open(path, encoding="utf-8", errors="replace").read()
        fm = frontmatter(text)
        desc = field(fm, "description")
        rows.append({
            "name": name,
            "display": field(fm, "name") or name,
            "desc": desc,
            "category": category_of(packs, name),
            "active": active,
            "path": path.replace("\\", "/"),
            "size": len(fm),
        })
    return rows


def build_doc(row):
    return {
        "tokens": Counter(
            tokenize(row["name"]) * 4
            + tokenize(row["name"].replace("-", " ")) * 2
            + tokenize(row["category"]) * 3
            + tokenize(row["desc"])
        ),
        "length": 0,
    }


def reindex():
    rows = scan(True) + scan(False)
    docs = []
    for row in rows:
        doc = build_doc(row)
        doc["length"] = sum(doc["tokens"].values()) or 1
        docs.append(doc)
    df = Counter()
    for doc in docs:
        df.update(doc["tokens"].keys())
    payload = {
        "version": 2,
        "home": CODEX_HOME,
        "count": len(rows),
        "rows": rows,
    }
    io.open(INDEX_PATH, "w", encoding="utf-8").write(
        json.dumps(payload, ensure_ascii=False)
    )
    return len(rows), len(df)


# ------------------------------------------------------------------ searching
def load_index():
    if not os.path.exists(INDEX_PATH):
        raise SystemExit("index missing - run: python skillfind.py --reindex")
    return json.load(io.open(INDEX_PATH, encoding="utf-8"))


def token_weight(token):
    if token in EN_STOP:
        return 0.0
    if len(token) == 1 and CJK.match(token):
        return 0.0 if token in CJK_STOP else 0.35
    return 1.0


def load_concepts():
    """Return (token_map, phrase_list, routes) for cross-language query expansion."""
    token_map = {}
    phrases = []
    routes = []
    if not os.path.exists(ALIAS_PATH):
        return token_map, phrases, routes
    data = json.load(io.open(ALIAS_PATH, encoding="utf-8"))
    for group in data.get("concepts", []):
        members = [g for g in group if g]
        for member in members:
            norm_member = re.sub(r"\s+", "", member.lower())
            if not norm_member:
                continue
            phrases.append((norm_member, members))
            for token in tokenize(member):
                token_map.setdefault(token, set()).update(members)
    phrases.sort(key=lambda item: -len(item[0]))
    for route in data.get("routes", []):
        triggers = [re.sub(r"\s+", "", w.lower()) for w in route.get("when", [])]
        targets = [name.lower() for name in route.get("skills", []) if name]
        triggers = [t for t in triggers if t]
        if triggers and targets:
            routes.append((triggers, targets))
    return token_map, phrases, routes


def expand_query(query, token_map, phrases):
    """Base weights from the query plus lower-weight weights from concept siblings."""
    base = Counter()
    for token in tokenize(query):
        weight = token_weight(token)
        if weight:
            base[token] = max(base[token], weight)

    extra_members = set()
    normalized = re.sub(r"\s+", "", query.lower())
    for phrase, members in phrases:
        if len(phrase) >= 2 and phrase in normalized:
            extra_members.update(members)
    for token in list(base):
        if token in token_map:
            extra_members.update(token_map[token])

    extra = Counter()
    for member in extra_members:
        for token in tokenize(member):
            weight = token_weight(token)
            if not weight or token in base:
                continue
            extra[token] = max(extra[token], 0.55 * weight)
    return base, extra


def search(index, query, top, active_only):
    rows = index["rows"]
    if active_only:
        rows = [r for r in rows if r["active"]]
    docs = []
    df = Counter()
    for row in rows:
        doc = build_doc(row)
        doc["length"] = sum(doc["tokens"].values()) or 1
        docs.append(doc)
        df.update(doc["tokens"].keys())
    total = len(docs) or 1
    avg_len = sum(d["length"] for d in docs) / total

    token_map, phrases, routes = load_concepts()
    base, extra = expand_query(query, token_map, phrases)
    q_tokens = Counter()
    q_tokens.update(base)
    for token, weight in extra.items():
        q_tokens[token] = q_tokens.get(token, 0) + weight
    q_norm = re.sub(r"\s+", "", query.lower())
    routed = {}
    for triggers, targets in routes:
        if any(trigger in q_norm for trigger in triggers):
            for index, target in enumerate(targets):
                bonus = max(2.0, 14.0 - 1.1 * index)
                routed[target] = max(routed.get(target, 0.0), bonus)
    if not q_tokens and not routed:
        return []
    base_count = len(base) or 1
    results = []
    for row, doc in zip(rows, docs):
        score = 0.0
        matched = set()
        name_tokens = set(tokenize(row["name"]))
        for token, q_weight in q_tokens.items():
            freq = doc["tokens"].get(token, 0)
            if not freq:
                continue
            matched.add(token)
            idf = math.log(1 + (total - df[token] + 0.5) / (df[token] + 0.5))
            denom = freq + 1.2 * (1 - 0.75 + 0.75 * doc["length"] / avg_len)
            score += idf * (freq * 2.2) / denom * q_weight
        name_hits = len(name_tokens & set(base))
        score += 3.2 * name_hits
        route_bonus = routed.get(row["name"].lower(), 0.0)
        if route_bonus:
            score += route_bonus
            matched.add("routed")
        if row["name"].replace("-", " ").replace("_", " ") in q_norm or row["name"] in q_norm:
            score += 12.0
            matched.add(row["name"])
        if not matched:
            continue
        overlap = len(set(base) & matched) / base_count
        score *= 1 + 0.35 * overlap
        if row["active"]:
            score *= 1.06
        results.append((score, row, matched))
    results.sort(key=lambda item: (-item[0], item[1]["name"]))
    return results[:top]


def merge_cjk(tokens):
    """Collapse overlapping CJK bigrams into longer runs for display."""
    cjk_tokens = sorted((t for t in tokens if CJK.match(t) and len(t) > 1), key=len, reverse=True)
    kept = []
    for token in cjk_tokens:
        if any(token in bigger for bigger in kept):
            continue
        kept.append(token)
    merged = []
    for token in kept:
        for i, existing in enumerate(merged):
            if token[-1] == existing[0]:
                merged[i] = token + existing[1:]
                break
            if existing[-1] == token[0]:
                merged[i] = existing + token[1:]
                break
        else:
            merged.append(token)
    ascii_tokens = sorted(t for t in tokens if not CJK.match(t))
    return ascii_tokens + merged


def fmt_line(score, row, matched, width=96):
    status = "on " if row["active"] else "off"
    desc = row["desc"][:width]
    if len(row["desc"]) > width:
        desc += "..."
    terms = ",".join(merge_cjk(matched)[:7])
    return "%-5.1f [%s] %-30s %s\n            cat=%s  hits=%s\n            %s" % (
        score, status, row["name"], desc, row["category"], terms, row["path"],
    )


def cmd_stats(index):
    rows = index["rows"]
    active = [r for r in rows if r["active"]]
    cats = Counter(r["category"] for r in rows)
    print("indexed skills : %d" % len(rows))
    print("active         : %d" % len(active))
    print("parked         : %d" % (len(rows) - len(active)))
    print("active chars   : %d (~%d tokens)" % (
        sum(r["size"] for r in active), sum(r["size"] for r in active) // 4))
    print("categories     :")
    for cat, count in cats.most_common():
        print("  %-18s %d" % (cat, count))


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("query", nargs="*")
    parser.add_argument("-n", "--top", type=int, default=5)
    parser.add_argument("--reindex", action="store_true")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--list", dest="list_category")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--active-only", action="store_true")
    args = parser.parse_args()

    if args.reindex:
        count, vocab = reindex()
        print("reindexed %d skills, vocabulary %d" % (count, vocab))
        if not args.query and not args.stats and not args.list_category:
            return

    index = load_index()

    if args.stats:
        cmd_stats(index)
        return

    if args.list_category:
        rows = [r for r in index["rows"] if r["category"] == args.list_category]
        if not rows:
            print("no skills in category %s" % args.list_category)
            return
        for row in sorted(rows, key=lambda r: r["name"]):
            print("%-5s %-30s %s" % ("on" if row["active"] else "off", row["name"], row["desc"][:80]))
        return

    query = " ".join(args.query).strip()
    if not query:
        parser.print_help()
        return

    results = search(index, query, args.top, args.active_only)
    if args.json:
        print(json.dumps([
            {
                "score": round(score, 2),
                "name": row["name"],
                "active": row["active"],
                "category": row["category"],
                "path": row["path"],
                "description": row["desc"],
            }
            for score, row, _ in results
        ], ensure_ascii=False, indent=2))
        return
    if not results:
        print("no match for: %s" % query)
        return
    for score, row, matched in results:
        print(fmt_line(score, row, matched))
    print("")
    print("to use a parked skill now, read its SKILL.md path above directly,")
    print("or activate it for later turns:  skillctl on <name>")


if __name__ == "__main__":
    main()
