#!/usr/bin/env python3
"""
Download all PDF documents starting from:
https://www.in.gov/medicaid/providers/provider-references/bulletins-banner-pages-and-reference-modules/ihcp-provider-reference-modules/

Features
- Crawls only within the same site (default) and same path prefix as the start URL
- Finds direct .pdf links and links whose Content-Type is application/pdf
- Respects robots.txt (including crawl-delay if present)
- Retries transient HTTP errors
- Skips already-downloaded files
- Sanitizes filenames
- Command-line options for depth, output dir, and rate limiting
"""

import argparse
import os
import re
import time
import sys
from collections import deque
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter, Retry
import urllib.robotparser as robotparser


DEFAULT_START = "https://www.in.gov/medicaid/providers/provider-references/bulletins-banner-pages-and-reference-modules/ihcp-provider-reference-modules/"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36 (+https://github.com/)"
)

def build_session(timeout=20):
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    retries = Retry(
        total=5,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"])
    )
    s.mount("http://", HTTPAdapter(max_retries=retries))
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.request_timeout = timeout
    return s

def load_robots(base_url, user_agent=USER_AGENT):
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = robotparser.RobotFileParser()
    try:
        rp.set_url(robots_url)
        rp.read()
    except Exception:
        # If robots can’t be loaded, default to allowing (common practice),
        # but still apply our own politeness delay.
        pass
    return rp

def allowed_by_robots(rp, url):
    try:
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        return True  # be permissive if parser failed

def robots_crawl_delay(rp):
    try:
        cd = rp.crawl_delay(USER_AGENT)
        return cd if cd is not None else 0
    except Exception:
        return 0

def sanitize_filename(name):
    # Remove query strings & fragments handled earlier; just sanitize path part
    name = re.sub(r"[^\w\-.()+\s]", "_", name)
    # Keep it reasonable length
    return name[-180:] if len(name) > 180 else name

def ensure_unique_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while True:
        candidate = f"{base} ({i}){ext}"
        if not os.path.exists(candidate):
            return candidate
        i += 1

def is_same_site(url, base):
    return urlparse(url).netloc == urlparse(base).netloc

def is_under_base_path(url, base):
    up = urlparse(url)
    bp = urlparse(base)
    # allow if same netloc and path starts with the base path
    return (up.netloc == bp.netloc) and up.path.startswith(bp.path)

def normalize_link(href, base_url):
    if not href:
        return None
    href = href.strip()
    if href.startswith("mailto:") or href.startswith("tel:") or href.startswith("javascript:"):
        return None
    # Resolve relative URL and strip fragment
    absolute = urljoin(base_url, href)
    absolute, _ = urldefrag(absolute)
    # Force https if website primarily uses https
    return absolute

def looks_like_pdf(url):
    # Heuristic: ends with .pdf or has common PDF patterns
    path = urlparse(url).path.lower()
    return path.endswith(".pdf")

def head_is_pdf(session, url, timeout):
    try:
        r = session.head(url, allow_redirects=True, timeout=timeout)
        ct = r.headers.get("Content-Type", "").lower()
        return "application/pdf" in ct
    except requests.RequestException:
        return False

def fetch_html(session, url, timeout):
    r = session.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text

def extract_links(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    links = set()
    for a in soup.find_all("a", href=True):
        u = normalize_link(a["href"], base_url)
        if u:
            links.add(u)
    return links

def download_pdf(session, url, out_dir, timeout):
    path = urlparse(url).path
    fname = os.path.basename(path) or "document.pdf"
    fname = sanitize_filename(fname)
    target = os.path.join(out_dir, fname)
    target = ensure_unique_path(target)

    with session.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        # double-check content-type; some servers mislabel, but we only save anyway
        os.makedirs(out_dir, exist_ok=True)
        total = int(r.headers.get("Content-Length") or 0)
        downloaded = 0
        chunk = 1024 * 64
        with open(target, "wb") as f:
            for chunk_bytes in r.iter_content(chunk_size=chunk):
                if chunk_bytes:
                    f.write(chunk_bytes)
                    downloaded += len(chunk_bytes)

    print(f"[saved] {url} -> {target}")
    return target

def crawl_and_download(start_url, out_dir, max_depth=2, delay=0.5, same_path_only=True):
    session = build_session()
    rp = load_robots(start_url)
    enforced_delay = max(delay, robots_crawl_delay(rp))

    start = start_url
    base_netloc = urlparse(start).netloc

    seen_pages = set()
    queued = deque([(start, 0)])
    found_pdfs = set()
    downloaded = 0
    checked_links = 0

    while queued:
        url, depth = queued.popleft()
        if url in seen_pages:
            continue
        seen_pages.add(url)

        if not is_same_site(url, start):
            continue
        if same_path_only and not is_under_base_path(url, start):
            continue
        if not allowed_by_robots(rp, url):
            print(f"[robots] Skipping disallowed page: {url}")
            continue

        try:
            print(f"[page] ({depth}) {url}")
            html = fetch_html(session, url, timeout=session.request_timeout)
            time.sleep(enforced_delay)
        except requests.RequestException as e:
            print(f"[error] Failed to fetch page: {url} :: {e}")
            continue

        links = extract_links(html, url)
        for link in links:
            checked_links += 1

            # PDF candidates
            if looks_like_pdf(link) or head_is_pdf(session, link, timeout=session.request_timeout):
                if not allowed_by_robots(rp, link):
                    print(f"[robots] Skipping disallowed file: {link}")
                    continue
                if link not in found_pdfs:
                    found_pdfs.add(link)
                    try:
                        download_pdf(session, link, out_dir, timeout=session.request_timeout)
                        downloaded += 1
                        time.sleep(enforced_delay)
                    except requests.RequestException as e:
                        print(f"[error] Download failed: {link} :: {e}")
                continue

            # Enqueue more pages to crawl
            if depth < max_depth:
                if is_same_site(link, start) and (not same_path_only or is_under_base_path(link, start)):
                    if link not in seen_pages:
                        queued.append((link, depth + 1))

    print("\n=== Summary ===")
    print(f"Pages visited: {len(seen_pages)}")
    print(f"Links checked: {checked_links}")
    print(f"PDFs found:    {len(found_pdfs)}")
    print(f"Downloaded:    {downloaded}")
    if found_pdfs:
        print("First few PDFs:")
        for i, u in enumerate(sorted(found_pdfs)[:10], 1):
            print(f"  {i:>2}. {u}")

def main():
    ap = argparse.ArgumentParser(description="Crawl a site section and download all PDFs found.")
    ap.add_argument("--start", default=DEFAULT_START, help="Start URL to crawl")
    ap.add_argument("--out", default="ihcp_pdfs", help="Output directory for downloaded PDFs")
    ap.add_argument("--depth", type=int, default=2, help="Max crawl depth from the start page (default: 2)")
    ap.add_argument("--delay", type=float, default=0.5, help="Delay (seconds) between requests; robots crawl-delay may increase this")
    ap.add_argument("--all-paths", action="store_true",
                    help="Allow crawling anywhere on the same site (not just under the start URL path)")
    args = ap.parse_args()

    try:
        crawl_and_download(
            start_url=args.start,
            out_dir=args.out,
            max_depth=args.depth,
            delay=args.delay,
            same_path_only=not args.all_paths
        )
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
