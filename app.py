import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
import json
import os
import time


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}

TIMEOUT = 10


def get_page(url):
    """دریافت محتوای یک صفحه"""

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT
        )

        response.raise_for_status()

        return response

    except requests.exceptions.Timeout:
        print(f"Timeout: {url}")

    except requests.exceptions.ConnectionError:
        print(f"Connection Error: {url}")

    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error: {url} - {e}")

    except requests.exceptions.RequestException as e:
        print(f"Request Error: {url} - {e}")

    return None


def check_robots(url):
    """بررسی robots.txt"""

    parsed_url = urlparse(url)

    robots_url = (
        f"{parsed_url.scheme}://"
        f"{parsed_url.netloc}/robots.txt"
    )

    result = {
        "url": robots_url,
        "exists": False,
        "allowed": True
    }

    try:
        response = requests.get(
            robots_url,
            headers=HEADERS,
            timeout=TIMEOUT
        )

        if response.status_code == 200:
            result["exists"] = True

            robot_parser = RobotFileParser()
            robot_parser.set_url(robots_url)
            robot_parser.parse(response.text.splitlines())

            result["allowed"] = robot_parser.can_fetch(
                HEADERS["User-Agent"],
                url
            )

    except requests.exceptions.RequestException:
        pass

    return result


def check_sitemap(url):
    """بررسی sitemap.xml"""

    parsed_url = urlparse(url)

    sitemap_url = (
        f"{parsed_url.scheme}://"
        f"{parsed_url.netloc}/sitemap.xml"
    )

    result = {
        "url": sitemap_url,
        "exists": False,
        "status_code": None
    }

    try:
        response = requests.get(
            sitemap_url,
            headers=HEADERS,
            timeout=TIMEOUT
        )

        result["status_code"] = response.status_code

        if response.status_code == 200:
            result["exists"] = True

    except requests.exceptions.RequestException:
        pass

    return result


def check_link(url):
    """بررسی وضعیت یک لینک"""

    try:
        response = requests.head(
            url,
            headers=HEADERS,
            timeout=5,
            allow_redirects=True
        )

        if response.status_code == 405:
            response = requests.get(
                url,
                headers=HEADERS,
                timeout=5,
                stream=True
            )

        return {
            "url": url,
            "status_code": response.status_code,
            "working": response.status_code < 400
        }

    except requests.exceptions.RequestException:
        return {
            "url": url,
            "status_code": None,
            "working": False
        }


def analyze_website(url):
    """تحلیل کامل وب‌سایت"""

    print("\nشروع بررسی وب‌سایت...")
    print("-" * 50)

    response = get_page(url)

    if not response:
        return {
            "error": "دریافت اطلاعات وب‌سایت با مشکل مواجه شد."
        }

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    parsed_url = urlparse(url)
    domain = parsed_url.netloc

    # --------------------------------
    # اطلاعات اصلی صفحه
    # --------------------------------

    title_tag = soup.find("title")

    title = (
        title_tag.get_text(strip=True)
        if title_tag
        else ""
    )

    description_tag = soup.find(
        "meta",
        attrs={"name": "description"}
    )

    description = (
        description_tag.get("content", "").strip()
        if description_tag
        else ""
    )

    # --------------------------------
    # تیترها
    # --------------------------------

    headings = {
        "h1": [
            h.get_text(" ", strip=True)
            for h in soup.find_all("h1")
        ],
        "h2": [
            h.get_text(" ", strip=True)
            for h in soup.find_all("h2")
        ],
        "h3": [
            h.get_text(" ", strip=True)
            for h in soup.find_all("h3")
        ]
    }

    # --------------------------------
    # Canonical
    # --------------------------------

    canonical_tag = soup.find(
        "link",
        rel="canonical"
    )

    canonical = ""

    if canonical_tag:
        canonical = canonical_tag.get("href", "")

    # --------------------------------
    # زبان صفحه
    # --------------------------------

    html_tag = soup.find("html")

    language = ""

    if html_tag:
        language = html_tag.get("lang", "")

    # --------------------------------
    # Viewport
    # --------------------------------

    viewport_tag = soup.find(
        "meta",
        attrs={"name": "viewport"}
    )

    viewport = ""

    if viewport_tag:
        viewport = viewport_tag.get("content", "")

    # --------------------------------
    # Open Graph
    # --------------------------------

    og_tags = {}

    for tag in soup.find_all(
        "meta",
        attrs={"property": True}
    ):
        property_name = tag.get("property")

        if property_name.startswith("og:"):
            og_tags[property_name] = tag.get(
                "content",
                ""
            )

    # --------------------------------
    # لینک‌ها
    # --------------------------------

    internal_links = []
    external_links = []

    for a in soup.find_all("a", href=True):

        href = a["href"].strip()

        if not href:
            continue

        if href.startswith("#"):
            continue

        if href.startswith("mailto:"):
            continue

        if href.startswith("tel:"):
            continue

        full_url = urljoin(url, href)

        parsed_link = urlparse(full_url)

        if parsed_link.netloc == domain:
            if full_url not in internal_links:
                internal_links.append(full_url)
        else:
            if full_url not in external_links:
                external_links.append(full_url)

    # --------------------------------
    # تصاویر
    # --------------------------------

    images = []

    for img in soup.find_all("img"):

        src = img.get("src", "").strip()

        if not src:
            continue

        image_url = urljoin(url, src)

        alt = img.get("alt")

        images.append({
            "url": image_url,
            "alt": alt if alt else "",
            "has_alt": bool(alt and alt.strip())
        })

    # --------------------------------
    # بررسی لینک‌های داخلی
    # --------------------------------

    broken_links = []

    print("\nبررسی لینک‌های داخلی...")

    # برای اینکه تعداد درخواست‌ها خیلی زیاد نشود
    links_to_check = internal_links[:30]

    for index, link in enumerate(links_to_check, 1):

        print(
            f"Checking {index}/{len(links_to_check)}: "
            f"{link}"
        )

        link_result = check_link(link)

        if not link_result["working"]:
            broken_links.append(link_result)

        time.sleep(0.2)

    # --------------------------------
    # متن صفحه
    # --------------------------------

    for tag in soup([
        "script",
        "style",
        "noscript"
    ]):
        tag.decompose()

    page_text = soup.get_text(
        " ",
        strip=True
    )

    # --------------------------------
    # بررسی robots
    # --------------------------------

    print("\nبررسی robots.txt...")

    robots = check_robots(url)

    # --------------------------------
    # بررسی sitemap
    # --------------------------------

    print("بررسی sitemap.xml...")

    sitemap = check_sitemap(url)

    # --------------------------------
    # گزارش SEO
    # --------------------------------

    seo = {
        "title": {
            "exists": bool(title),
            "length": len(title),
            "status": (
                "خوب"
                if 30 <= len(title) <= 60
                else "نیاز به بررسی"
            )
        },

        "description": {
            "exists": bool(description),
            "length": len(description),
            "status": (
                "خوب"
                if 70 <= len(description) <= 160
                else "نیاز به بررسی"
            )
        },

        "h1": {
            "count": len(headings["h1"]),
            "status": (
                "خوب"
                if len(headings["h1"]) == 1
                else "نیاز به بررسی"
            )
        },

        "canonical": {
            "exists": bool(canonical)
        },

        "language": {
            "exists": bool(language),
            "value": language
        },

        "viewport": {
            "exists": bool(viewport)
        },

        "open_graph": {
            "exists": bool(og_tags),
            "tags": og_tags
        },

        "images": {
            "total": len(images),
            "without_alt": len([
                img
                for img in images
                if not img["has_alt"]
            ])
        },

        "links": {
            "internal": len(internal_links),
            "external": len(external_links),
            "broken": len(broken_links)
        }
    }

    # --------------------------------
    # ساخت نتیجه نهایی
    # --------------------------------

    data = {
        "website": url,

        "status_code": response.status_code,

        "title": title,

        "description": description,

        "seo": seo,

        "headings": headings,

        "canonical": canonical,

        "language": language,

        "viewport": viewport,

        "open_graph": og_tags,

        "links": {
            "internal": internal_links,
            "external": external_links,
            "broken": broken_links
        },

        "images": images,

        "robots": robots,

        "sitemap": sitemap,

        "text_length": len(page_text),

        "text": page_text
    }

    return data


def save_json(data):
    """ذخیره گزارش JSON"""

    with open(
        "website_report.json",
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=4
        )


def save_html_report(data):
    """ساخت گزارش HTML"""

    seo = data.get("seo", {})

    title = data.get("title", "")
    description = data.get("description", "")

    h1_count = len(
        data.get("headings", {}).get("h1", [])
    )

    internal_count = len(
        data.get("links", {}).get("internal", [])
    )

    external_count = len(
        data.get("links", {}).get("external", [])
    )

    broken_count = len(
        data.get("links", {}).get("broken", [])
    )

    images = data.get("images", [])

    images_without_alt = len([
        image
        for image in images
        if not image["has_alt"]
    ])

    html = f"""
<!DOCTYPE html>
<html lang="fa" dir="rtl">

<head>

<meta charset="UTF-8">

<meta name="viewport"
content="width=device-width, initial-scale=1.0">

<title>گزارش بررسی وب‌سایت</title>

<style>

body {{
    font-family: Tahoma, Arial, sans-serif;
    max-width: 1000px;
    margin: 40px auto;
    padding: 20px;
    background: #f5f5f5;
    line-height: 1.8;
}}

.card {{
    background: white;
    padding: 20px;
    margin-bottom: 20px;
    border-radius: 10px;
}}

h1, h2 {{
    color: #222;
}}

table {{
    width: 100%;
    border-collapse: collapse;
}}

td, th {{
    padding: 10px;
    border: 1px solid #ddd;
    text-align: right;
}}

.good {{
    color: green;
}}

.warning {{
    color: orange;
}}

</style>

</head>

<body>

<h1>گزارش بررسی وب‌سایت</h1>

<div class="card">

<h2>اطلاعات اصلی</h2>

<p>
<strong>آدرس:</strong>
{data.get("website", "")}
</p>

<p>
<strong>Title:</strong>
{title}
</p>

<p>
<strong>Description:</strong>
{description}
</p>

</div>


<div class="card">

<h2>بررسی SEO</h2>

<table>

<tr>
<th>مورد</th>
<th>وضعیت</th>
</tr>

<tr>
<td>Title</td>
<td>{seo.get("title", {}).get("status", "")}</td>
</tr>

<tr>
<td>Description</td>
<td>{seo.get("description", {}).get("status", "")}</td>
</tr>

<tr>
<td>H1</td>
<td>{h1_count}</td>
</tr>

<tr>
<td>Canonical</td>
<td>{data.get("canonical", "ندارد")}</td>
</tr>

<tr>
<td>Language</td>
<td>{data.get("language", "ندارد")}</td>
</tr>

<tr>
<td>Viewport</td>
<td>
{"دارد" if data.get("viewport") else "ندارد"}
</td>
</tr>

</table>

</div>


<div class="card">

<h2>لینک‌ها</h2>

<p>
لینک داخلی:
{internal_count}
</p>

<p>
لینک خارجی:
{external_count}
</p>

<p>
لینک خراب:
{broken_count}
</p>

</div>


<div class="card">

<h2>تصاویر</h2>

<p>
تعداد تصاویر:
{len(images)}
</p>

<p>
تصاویر بدون Alt:
{images_without_alt}
</p>

</div>


<div class="card">

<h2>Robots.txt</h2>

<p>
{"وجود دارد" if data.get("robots", {}).get("exists")
else "پیدا نشد"}
</p>

</div>


<div class="card">

<h2>Sitemap.xml</h2>

<p>
{"وجود دارد" if data.get("sitemap", {}).get("exists")
else "پیدا نشد"}
</p>

</div>


<div class="card">

<h2>Headings</h2>

<h3>H1</h3>

<ul>
"""

    for heading in data["headings"]["h1"]:
        html += f"<li>{heading}</li>"

    html += """
</ul>

<h3>H2</h3>

<ul>
"""

    for heading in data["headings"]["h2"]:
        html += f"<li>{heading}</li>"

    html += """
</ul>

<h3>H3</h3>

<ul>
"""

    for heading in data["headings"]["h3"]:
        html += f"<li>{heading}</li>"

    html += """
</ul>

</div>

</body>

</html>
"""

    with open(
        "website_report.html",
        "w",
        encoding="utf-8"
    ) as file:

        file.write(html)


def print_summary(data):
    """نمایش خلاصه گزارش"""

    if "error" in data:
        print("\nخطا:")
        print(data["error"])
        return

    seo = data["seo"]

    print("\n")
    print("=" * 50)
    print("گزارش نهایی وب‌سایت")
    print("=" * 50)

    print(f"URL: {data['website']}")
    print(f"Status Code: {data['status_code']}")

    print("\nSEO")
    print("-" * 30)

    print(
        f"Title: {seo['title']['length']} کاراکتر"
    )

    print(
        f"Description: "
        f"{seo['description']['length']} کاراکتر"
    )

    print(
        f"H1: "
        f"{seo['h1']['count']}"
    )

    print(
        f"تصاویر: "
        f"{seo['images']['total']}"
    )

    print(
        f"تصاویر بدون Alt: "
        f"{seo['images']['without_alt']}"
    )

    print(
        f"لینک داخلی: "
        f"{seo['links']['internal']}"
    )

    print(
        f"لینک خارجی: "
        f"{seo['links']['external']}"
    )

    print(
        f"لینک خراب: "
        f"{seo['links']['broken']}"
    )

    print(
        f"Robots.txt: "
        f"{'دارد' if data['robots']['exists'] else 'ندارد'}"
    )

    print(
        f"Sitemap: "
        f"{'دارد' if data['sitemap']['exists'] else 'ندارد'}"
    )

    print("\nفایل‌های خروجی:")
    print("website_report.json")
    print("website_report.html")

    print("=" * 50)


# اجرای برنامه
if __name__ == "__main__":

    url = "https://alifasihi.ir"

    result = analyze_website(url)

    if "error" not in result:

        save_json(result)

        save_html_report(result)

    print_summary(result)
