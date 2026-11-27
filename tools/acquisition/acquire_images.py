"""
Generic Playwright image gallery crawler for benchmark source acquisition.

Crawls image galleries (NACHI, OSHA, CSB, etc.), downloads images with their
captions/alt text, and writes candidate JSONL records.

Usage:
  # Crawl InterNACHI piping gallery
  python scripts/acquire_images.py \\
      --url "https://www.nachi.org/gallery/piping" \\
      --industry plumbing \\
      --source nachi_piping_gallery \\
      --license educational_use

  # Crawl OSHA electrical photos
  python scripts/acquire_images.py \\
      --url "https://www.osha.gov/electrical" \\
      --industry electrical \\
      --source osha_electrical_photos \\
      --license public_domain_us_gov

  # Custom CSS selectors for non-standard galleries
  python scripts/acquire_images.py \\
      --url "https://example.com/gallery" \\
      --industry construction \\
      --source example_gallery \\
      --img-selector "img.gallery-photo" \\
      --caption-selector ".photo-caption"

Optional env:
  ACQUIRE_HEADLESS=1   Run headless browser (default: 1)
  ACQUIRE_MAX_IMAGES=200  Max images per gallery
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

_SERVER_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SERVER_ROOT not in sys.path:
    sys.path.insert(0, _SERVER_ROOT)

HEADLESS = os.getenv("ACQUIRE_HEADLESS", "1") == "1"
MAX_IMAGES = int(os.getenv("ACQUIRE_MAX_IMAGES", "200"))

CANDIDATES_DIR = Path(_SERVER_ROOT) / "candidates"
IMAGES_DIR = Path(_SERVER_ROOT) / "fixtures" / "images"

MIN_IMAGE_BYTES = 5_000
MIN_IMAGE_DIM = 80


def _write_candidate(record: dict, source: str):
    CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CANDIDATES_DIR / f"{source}.jsonl"
    with open(out_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _save_image_from_url(url: str, industry: str, source: str, idx: int) -> str | None:
    """Download image from URL and save to fixtures/images/{industry}/."""
    try:
        req = Request(url, headers={"User-Agent": "FieldOpsBench/2.0 (benchmark acquisition)"})
        with urlopen(req, timeout=30) as resp:
            data = resp.read()
    except Exception as e:
        print(f"    Failed to download {url[:60]}: {e}")
        return None

    if len(data) < MIN_IMAGE_BYTES:
        return None

    ext = "jpg"
    if url.lower().endswith(".png"):
        ext = "png"
    elif url.lower().endswith(".webp"):
        ext = "webp"

    h = hashlib.md5(data).hexdigest()[:8]
    filename = f"{source}-{idx:03d}-{h}.{ext}"
    industry_dir = IMAGES_DIR / industry
    industry_dir.mkdir(parents=True, exist_ok=True)
    dest = industry_dir / filename
    dest.write_bytes(data)
    return f"fixtures/images/{industry}/{filename}"


async def crawl_gallery(
    url: str,
    industry: str,
    source: str,
    license_tag: str,
    img_selector: str | None = None,
    caption_selector: str | None = None,
    follow_links: bool = False,
    max_images: int = MAX_IMAGES,
) -> int:
    """Crawl an image gallery page and extract images with captions."""
    from playwright.async_api import async_playwright

    count = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(3)

            # Scroll to trigger lazy-loading
            for _ in range(10):
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await asyncio.sleep(0.5)
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(1)

            # Extract image data from the page
            img_sel = img_selector or "img"
            caption_sel = caption_selector or ""

            image_data = await page.evaluate(f"""
                () => {{
                    const results = [];
                    const imgs = document.querySelectorAll('{img_sel}');
                    imgs.forEach((img, idx) => {{
                        const src = img.src || img.getAttribute('data-src') || img.getAttribute('data-lazy-src') || '';
                        if (!src || src.startsWith('data:')) return;

                        const width = img.naturalWidth || img.width || 0;
                        const height = img.naturalHeight || img.height || 0;
                        if (width < {MIN_IMAGE_DIM} || height < {MIN_IMAGE_DIM}) return;

                        let caption = img.alt || img.title || '';

                        // Try to find a caption element nearby
                        const captionSel = '{caption_sel}';
                        if (captionSel) {{
                            const parent = img.closest('figure, .gallery-item, .photo-item, li, .card, article');
                            if (parent) {{
                                const cap = parent.querySelector(captionSel);
                                if (cap) caption = cap.textContent.trim();
                            }}
                        }} else {{
                            const parent = img.closest('figure, .gallery-item, .photo-item, li, .card, article');
                            if (parent) {{
                                const cap = parent.querySelector('figcaption, .caption, .photo-caption, .description, p');
                                if (cap) caption = cap.textContent.trim();
                            }}
                        }}

                        results.push({{
                            src: src,
                            alt: img.alt || '',
                            caption: caption,
                            width: width,
                            height: height,
                        }});
                    }});
                    return results;
                }}
            """)

            print(f"  Found {len(image_data)} images on page")

            # Deduplicate by URL
            seen_urls = set()
            unique_images = []
            for img in image_data:
                if img["src"] not in seen_urls:
                    seen_urls.add(img["src"])
                    unique_images.append(img)
            image_data = unique_images[:max_images]
            print(f"  {len(image_data)} unique images after dedup (max {max_images})")

            # If follow_links is set, also collect sub-page links
            sub_urls = []
            if follow_links:
                sub_urls = await page.evaluate("""
                    () => {
                        const links = [];
                        document.querySelectorAll('a[href]').forEach(a => {
                            const href = a.href;
                            if (href && !href.includes('#') && !href.endsWith('.pdf')) {
                                const text = a.textContent.trim().toLowerCase();
                                if (text && text.length > 3 && text.length < 100) {
                                    links.push({href, text});
                                }
                            }
                        });
                        return links;
                    }
                """)

            # Download and save images
            for img in image_data:
                img_url = img["src"]
                if not img_url.startswith("http"):
                    continue

                rel_path = _save_image_from_url(img_url, industry, source, count)
                if not rel_path:
                    continue

                caption = img.get("caption", "") or img.get("alt", "")

                record = {
                    "candidate_id": f"{source}-{count:03d}",
                    "industry": industry,
                    "source": source,
                    "source_url": img_url,
                    "modality": "image_plus_lookup",
                    "image_path": rel_path,
                    "image_caption": caption[:500],
                    "context_text": caption[:500],
                    "extracted_equipment": None,
                    "extracted_fault": None,
                    "extracted_fix": None,
                    "gold_verified": False,
                    "license": license_tag,
                }
                _write_candidate(record, source)
                count += 1
                print(f"    [{count}] {img_url[:60]}... caption: {caption[:40]}")

            # Crawl sub-pages if follow_links
            if follow_links and sub_urls:
                base_domain = url.split("//")[1].split("/")[0] if "//" in url else ""
                for sub in sub_urls[:20]:
                    sub_href = sub["href"]
                    if base_domain and base_domain not in sub_href:
                        continue
                    if count >= max_images:
                        break

                    try:
                        await page.goto(sub_href, wait_until="networkidle", timeout=15000)
                        await asyncio.sleep(2)

                        sub_images = await page.evaluate(f"""
                            () => {{
                                const results = [];
                                document.querySelectorAll('{img_sel}').forEach(img => {{
                                    const src = img.src || '';
                                    if (!src || src.startsWith('data:')) return;
                                    const w = img.naturalWidth || img.width || 0;
                                    const h = img.naturalHeight || img.height || 0;
                                    if (w < {MIN_IMAGE_DIM} || h < {MIN_IMAGE_DIM}) return;
                                    let caption = img.alt || img.title || '';
                                    const parent = img.closest('figure, .gallery-item, li, article');
                                    if (parent) {{
                                        const cap = parent.querySelector('figcaption, .caption, p');
                                        if (cap) caption = cap.textContent.trim();
                                    }}
                                    results.push({{ src, caption }});
                                }});
                                return results;
                            }}
                        """)

                        for si in sub_images:
                            if count >= max_images:
                                break
                            if si["src"] in seen_urls:
                                continue
                            seen_urls.add(si["src"])

                            rel_path = _save_image_from_url(si["src"], industry, source, count)
                            if not rel_path:
                                continue

                            record = {
                                "candidate_id": f"{source}-{count:03d}",
                                "industry": industry,
                                "source": source,
                                "source_url": si["src"],
                                "modality": "image_plus_lookup",
                                "image_path": rel_path,
                                "image_caption": si.get("caption", "")[:500],
                                "context_text": f"From sub-page: {sub['text'][:60]}. {si.get('caption', '')}",
                                "extracted_equipment": None,
                                "extracted_fault": None,
                                "extracted_fix": None,
                                "gold_verified": False,
                                "license": license_tag,
                            }
                            _write_candidate(record, source)
                            count += 1
                            print(f"    [{count}] (sub) {si['src'][:60]}...")

                    except Exception as e:
                        print(f"    Sub-page error {sub_href[:60]}: {e}")

        except Exception as e:
            print(f"  Error crawling gallery: {e}")
        finally:
            await browser.close()

    return count


async def main():
    parser = argparse.ArgumentParser(description="Crawl image galleries for benchmark candidates")
    parser.add_argument("--url", required=True, help="Gallery page URL")
    parser.add_argument("--industry", required=True, help="Industry tag")
    parser.add_argument("--source", required=True, help="Source identifier")
    parser.add_argument("--license", default="check_terms", help="License tag")
    parser.add_argument("--img-selector", default=None, help="CSS selector for images")
    parser.add_argument("--caption-selector", default=None, help="CSS selector for captions")
    parser.add_argument("--follow-links", action="store_true", help="Follow sub-page links")
    parser.add_argument("--max-images", type=int, default=MAX_IMAGES, help="Max images to download")
    args = parser.parse_args()

    print(f"\n{'=' * 60}")
    print(f"  Benchmark Image Gallery Crawler")
    print(f"  URL:      {args.url}")
    print(f"  Industry: {args.industry}")
    print(f"  Source:   {args.source}")
    print(f"  License:  {args.license}")
    print(f"  Follow:   {args.follow_links}")
    print(f"{'=' * 60}\n")

    start = time.monotonic()
    count = await crawl_gallery(
        url=args.url,
        industry=args.industry,
        source=args.source,
        license_tag=args.license,
        img_selector=args.img_selector,
        caption_selector=args.caption_selector,
        follow_links=args.follow_links,
        max_images=args.max_images,
    )

    elapsed = time.monotonic() - start
    print(f"\n{'=' * 60}")
    print(f"  Done. Downloaded {count} images in {elapsed:.1f}s")
    print(f"  Output: {CANDIDATES_DIR / f'{args.source}.jsonl'}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
