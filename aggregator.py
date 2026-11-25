#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自家爬虫 — 公开免费节点聚合器（GitHub Actions 版）

做的事：
  1. 从一批公开免费节点源抓取 Clash 格式的节点列表
  2. 按 服务器+端口+协议+凭据 去重
  3. 预筛：只保留被 2 个以上源同时收录的节点（多源收录 = 有人在维护，存活概率更高），
     再按地区只留美国/新加坡/日本/香港/韩国/台湾，按收录数排序取前 100 条精品
  4. 输出 clash-udl4ke8um5.yaml（完整 Clash 配置，含自动选择组）+ stats.txt（本次统计）

说明：本脚本不在服务器端测活（测的也不是使用者本人的线路），
节点是否能用、快不快，由使用者客户端在自己的线路上测。
"""
import ipaddress
import json
import time
import urllib.request

import yaml

SOURCES = [
    ("NoMoreWalls", "https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list.meta.yml"),
    ("Barabama", "https://raw.githubusercontent.com/Barabama/FreeNodes/main/nodes/clashmeta.yaml"),
    ("ermaozi", "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/clash.yml"),
    ("free18", "https://raw.githubusercontent.com/free18/v2ray/main/c.yaml"),
    ("marshall", "https://raw.githubusercontent.com/marshall888666/free_clash_subscribe/main/source/clash-meta.yaml"),
    ("ripaojiedian", "https://raw.githubusercontent.com/ripaojiedian/freenode/main/clash"),
    ("mfuu", "https://raw.githubusercontent.com/mfuu/FreeProxies/master/sub.yaml"),
    ("V2RayAggregator", "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge_yaml.yml"),
    ("AutoMerge", "https://raw.githubusercontent.com/chengaopan/AutoMergePublicNodes/master/list.yml"),
    ("anaer", "https://raw.githubusercontent.com/anaer/Sub/main/clash.yaml"),
]

CAP = 100
OUT_YAML = "clash-udl4ke8um5.yaml"
OUT_STATS = "stats.txt"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 zijia-crawler"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def is_bad_server(server):
    try:
        ip = ipaddress.ip_address(server)
        return (
            ip.is_private or ip.is_loopback or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified or ip.is_link_local
        )
    except ValueError:
        return False  # 域名形式，放行


# ---- 地区过滤：只留美国/新加坡/日本/香港/韩国/台湾（按节点名里的旗帜/国家名/地区代码判断） ----
import re

KEEP_FLAGS = ["🇺🇸", "🇸🇬", "🇯🇵", "🇭🇰", "🇰🇷", "🇹🇼"]
KEEP_CN = ["美国", "美國", "新加坡", "日本", "香港", "韩国", "韓國", "台湾", "台灣"]
KEEP_EN = ["usa", "united states", "america", "los angeles", "san jose", "dallas", "chicago",
           "seattle", "ashburn", "new york", "miami", "silicon", "las vegas", "phoenix", "denver",
           "atlanta", "portland", "fremont", "buffalo", "hawaii", "singapore", "japan", "hong kong",
           "hongkong", "korea", "taiwan"]
KEEP_CODE = re.compile(
    r"(?<![A-Za-z])(US|USA|SG|SGP|JP|JPN|HK|HKG|KR|KOR|TW|TWN)(?![A-Za-z])"
)


def keep_region(name):
    if any(f in name for f in KEEP_FLAGS):
        return True
    if any(c in name for c in KEEP_CN):
        return True
    low = name.lower()
    if any(e in low for e in KEEP_EN):
        return True
    return bool(KEEP_CODE.search(name))


def main():
    entries = {}
    per_source = []
    raw_total = 0
    for sname, url in SOURCES:
        try:
            data = yaml.safe_load(fetch(url))
            proxies = (data or {}).get("proxies") or []
            ok = 0
            for p in proxies:
                if not isinstance(p, dict) or not p.get("server") or not p.get("port"):
                    continue
                try:
                    port = int(p["port"])
                except Exception:
                    continue
                if not (1 <= port <= 65535):
                    continue
                server = str(p["server"]).strip()
                if not server or is_bad_server(server):
                    continue
                cred = str(p.get("uuid") or p.get("password") or p.get("cipher") or "")
                key = (str(p.get("type", "")).lower(), server.lower(), port, cred)
                raw_total += 1
                ok += 1
                if key not in entries:
                    q = dict(p)
                    q["server"] = server
                    q["port"] = port
                    entries[key] = {"proxy": q, "sources": set(), "count": 0}
                entries[key]["sources"].add(sname)
                entries[key]["count"] += 1
            per_source.append((sname, ok))
            print(f"[fetch] {sname}: {ok}")
        except Exception as e:
            per_source.append((sname, 0))
            print(f"[fetch] {sname}: FAIL {e}")

    uniq = list(entries.values())
    dist = {}
    for e in uniq:
        n = len(e["sources"])
        dist[n] = dist.get(n, 0) + 1
    print(f"[raw] {raw_total}  [unique] {len(uniq)}  [by-source-count] {dist}")

    # 被越多源收录排得越前；只收录 1 次的不要
    multi = [e for e in uniq if len(e["sources"]) >= 2]
    multi.sort(key=lambda e: (-len(e["sources"]), -e["count"]))
    # 地区过滤：只留美/新/日/港/韩/台
    multi = [e for e in multi if keep_region(str(e["proxy"].get("name") or ""))]
    kept = multi[:CAP]
    print(f"[region] asia+us kept: {len(kept)}")

    out_proxies, used = [], set()
    for e in kept:
        p = dict(e["proxy"])
        orig = str(p.get("name") or f"{p.get('type','node')}-{p['server']}").strip()
        name = f"[A自家爬虫] {orig}"
        base, n = name, 2
        while name in used:
            name = f"{base} #{n}"
            n += 1
        used.add(name)
        p["name"] = name
        out_proxies.append(p)

    names = [p["name"] for p in out_proxies]
    config = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "warning",
        "proxies": out_proxies,
        "proxy-groups": [
            {
                "name": "自动选择",
                "type": "url-test",
                "url": "http://www.gstatic.com/generate_204",
                "interval": 300,
                "tolerance": 80,
                "proxies": names,
            },
            {"name": "节点选择", "type": "select", "proxies": ["自动选择"] + names},
        ],
        "rules": ["MATCH,节点选择"],
    }
    with open(OUT_YAML, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False, width=1000)

    by_type = {}
    for p in out_proxies:
        t = str(p.get("type", "?"))
        by_type[t] = by_type.get(t, 0) + 1
    lines = [
        "自家爬虫 本次更新统计",
        f"更新时间(UTC): {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}",
        f"抓取总数: {raw_total}",
        f"去重后: {len(uniq)}",
        f"多源收录分布(源数:节点数): {json.dumps(dist, ensure_ascii=False)}",
        f"地区过滤后(仅美新日港韩台): {len(multi)}",
        f"最终打包: {len(out_proxies)}",
        f"按协议: {json.dumps(by_type, ensure_ascii=False)}",
        "各源条数: " + ", ".join(f"{n}={c}" for n, c in per_source),
    ]
    with open(OUT_STATS, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"[done] wrote {OUT_YAML} and {OUT_STATS}")


if __name__ == "__main__":
    main()
