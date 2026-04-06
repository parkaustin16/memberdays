import os
import re
import subprocess
import sys
import time
from datetime import datetime

import random
import ssl

import requests
import streamlit as st
import urllib3
from playwright.sync_api import sync_playwright

# Bypass SSL verification issues common on LG.com endpoints
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
ssl._create_default_https_context = ssl._create_unverified_context


def _secret(key: str, default=None):
    """Read from Streamlit secrets first, then env vars."""
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)

_STEALTH_INIT_SCRIPT = """
() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    window.chrome = { runtime: {} };
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);
}
"""


@st.cache_resource
def install_playwright_chromium() -> dict[str, str | bool | None]:
    """Install Chromium and validate Linux runtime dependencies.

    Returns a status dict instead of raising, so the app can render recovery steps.
    """

    def _missing_lib_from_error(error_text: str) -> str | None:
        match = re.search(r"error while loading shared libraries:\s*([^:\s]+)", error_text)
        return match.group(1) if match else None

    def _launch_smoke_test() -> str | None:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                browser.close()
            return None
        except Exception as exc:  # pragma: no cover - env specific
            return str(exc)

    def _try_install_linux_deps() -> tuple[bool, str]:
        deps_cmd = [sys.executable, "-m", "playwright", "install-deps", "chromium"]
        apt_cmd_no_update = [
            "sudo",
            "-n",
            "apt-get",
            "install",
            "-y",
            "libatk1.0-0",
            "libatk-bridge2.0-0",
            "libatspi2.0-0",
            "libgtk-3-0",
            "libnss3",
            "libxcomposite1",
            "libxdamage1",
            "libxfixes3",
            "libxrandr2",
            "libgbm1",
            "libasound2t64",
            "libpangocairo-1.0-0",
            "libpango-1.0-0",
            "libcairo2",
        ]
        apt_cmd = [
            "sudo",
            "-n",
            "apt-get",
            "install",
            "-y",
            "libatk1.0-0",
            "libatk-bridge2.0-0",
            "libatspi2.0-0",
            "libgtk-3-0",
            "libnss3",
            "libxcomposite1",
            "libxdamage1",
            "libxfixes3",
            "libxrandr2",
            "libgbm1",
            "libasound2t64",
            "libpangocairo-1.0-0",
            "libpango-1.0-0",
            "libcairo2",
        ]

        try:
            result = subprocess.run(deps_cmd, check=True, capture_output=True, text=True)
            return True, result.stdout
        except Exception as first_exc:  # pragma: no cover - env specific
            try:
                # Some devcontainers have broken apt update repos; try install first.
                result = subprocess.run(apt_cmd_no_update, check=True, capture_output=True, text=True)
                return True, result.stdout
            except Exception as no_update_exc:  # pragma: no cover - env specific
                try:
                    subprocess.run(["sudo", "-n", "apt-get", "update"], check=True, capture_output=True, text=True)
                    result = subprocess.run(apt_cmd, check=True, capture_output=True, text=True)
                    return True, result.stdout
                except Exception as second_exc:  # pragma: no cover - env specific
                    return False, f"{first_exc}\n{no_update_exc}\n{second_exc}"

    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
            capture_output=True,
            text=True,
        )

        launch_error = _launch_smoke_test()
        if not launch_error:
            return {
                "ready": True,
                "missing_lib": None,
                "message": "Playwright Chromium is ready.",
                "diagnostics": "",
            }

        missing_lib = _missing_lib_from_error(launch_error)
        diagnostics = launch_error

        if missing_lib and sys.platform.startswith("linux"):
            installed, details = _try_install_linux_deps()
            diagnostics = details
            if installed:
                launch_error = _launch_smoke_test()
                if not launch_error:
                    return {
                        "ready": True,
                        "missing_lib": None,
                        "message": "Playwright Chromium is ready after installing Linux dependencies.",
                        "diagnostics": details,
                    }
                diagnostics = launch_error

            manual_install = (
                "sudo apt-get install -y "
                "libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 libgtk-3-0 "
                "libnss3 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 "
                "libgbm1 libasound2t64 libpangocairo-1.0-0 libpango-1.0-0 libcairo2"
            )

            return {
                "ready": False,
                "missing_lib": missing_lib,
                "message": (
                    "Playwright is installed but Linux shared libraries are missing "
                    f"({missing_lib}). Run: {manual_install}"
                ),
                "diagnostics": diagnostics,
            }

        return {
            "ready": False,
            "missing_lib": None,
            "message": f"Playwright launch failed: {launch_error}",
            "diagnostics": diagnostics,
        }
    except Exception as exc:
        return {
            "ready": False,
            "missing_lib": None,
            "message": f"Failed to install Playwright Chromium: {exc}",
            "diagnostics": str(exc),
        }


REGIONS = {
    "Asia": [
        ("au", "Australia (AU)"),
        ("jp", "Japan (JP)"),
        ("hk", "Hong Kong (HK)"),
        ("tw", "Taiwan (TW)"),
        ("in", "India (IN)"),
        ("sg", "Singapore (SG)"),
        ("my", "Malaysia (MY)"),
        ("th", "Thailand (TH)"),
        ("vn", "Vietnam (VN)"),
        ("ph", "Philippines (PH)"),
        ("id", "Indonesia (ID)"),
    ],
    "Europe": [
        ("uk", "United Kingdom (UK)"),
        ("ch_fr", "Switzerland (CH_FR)"),
        ("ch_de", "Switzerland (CH_DE)"),
        ("fr", "France (FR)"),
        ("de", "Germany (DE)"),
        ("it", "Italy (IT)"),
        ("es", "Spain (ES)"),
        ("nl", "Netherlands (NL)"),
        ("cz", "Czech Republic (CZ)"),
        ("se", "Sweden (SE)"),
        ("pt", "Portugal (PT)"),
        ("hu", "Hungary (HU)"),
        ("pl", "Poland (PL)"),
        ("at", "Austria (AT)"),
    ],
    "LATAM": [
        ("mx", "Mexico (MX)"),
        ("br", "Brazil (BR)"),
        ("ar", "Argentina (AR)"),
        ("cl", "Chile (CL)"),
        ("co", "Colombia (CO)"),
        ("pe", "Peru (PE)"),
        ("pa", "Panama (PA)"),
    ],
    "MEA": [
        ("kz", "Kazakhstan (KZ)"),
        ("tr", "Turkiye (TR)"),
        ("eg_en", "Egypt (EG_EN)"),
        ("eg_ar", "Egypt (EG_AR)"),
        ("ma", "Morocco (MA)"),
        ("sa_en", "Saudi Arabia (SA_EN)"),
        ("sa", "Saudi Arabia (SA)"),
        ("za", "South Africa (ZA)"),
    ],
    "Canada": [
        ("ca_en", "Canada (CA_EN)"),
        ("ca_fr", "Canada (CA_FR)"),
    ],
}


def get_subsidiary_options() -> list[tuple[str, str]]:
    all_subs = []
    for group in REGIONS.values():
        all_subs.extend(group)
    return sorted(all_subs, key=lambda item: item[1])


def build_url_candidates(subsidiary_code: str) -> list[str]:
    """Build likely URL variants for prememberdays pages."""
    # Per-subsidiary overrides (used as the first/only candidate)
    _overrides: dict[str, str] = {
        "co": "https://www.lg.com/co/lg-members-days-2026/",
    }
    if subsidiary_code in _overrides:
        return [_overrides[subsidiary_code]]

    candidates = [f"https://www.lg.com/{subsidiary_code}/prememberdays/"]

    if "_" in subsidiary_code:
        candidates.append(f"https://www.lg.com/{subsidiary_code.replace('_', '-')}/prememberdays/")
        candidates.append(f"https://www.lg.com/{subsidiary_code.split('_')[0]}/prememberdays/")

    # Keep order, remove duplicates.
    return list(dict.fromkeys(candidates))


def resolve_target_url(subsidiary_code: str) -> tuple[str, int]:
    """Pick the first non-404 URL candidate."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    fallback_url = build_url_candidates(subsidiary_code)[0]
    fallback_status = 0

    for candidate in build_url_candidates(subsidiary_code):
        try:
            response = requests.get(candidate, timeout=15, allow_redirects=True, headers=headers)
            status = response.status_code
            if status != 404:
                return candidate, status
            fallback_status = status
        except Exception:
            continue

    return fallback_url, fallback_status


def upload_to_cloudinary(file_path: str, subsidiary_code: str, mode: str) -> str | None:
    """Upload screenshot to Cloudinary and return the secure URL, or None on failure."""
    import hashlib
    import io
    from PIL import Image

    cloud_name = _secret("CLOUDINARY_CLOUD_NAME")
    api_key = _secret("CLOUDINARY_API_KEY")
    api_secret = _secret("CLOUDINARY_API_SECRET")

    if not all([cloud_name, api_key, api_secret]):
        return None

    # Resize PNG to 2560px wide (from 3840px 2×DPR) — lossless, ~4MB, still 2.5K crisp
    img = Image.open(file_path).convert("RGB")
    target_w = 2560
    if img.width > target_w:
        ratio = target_w / img.width
        img = img.resize((target_w, int(img.height * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    timestamp = int(time.time())
    folder = f"memberdays/{subsidiary_code}/{mode}"
    public_id = f"{subsidiary_code}_{mode}_prememberdays_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Parameters must be sorted alphabetically before signing (exclude api_key, file, resource_type)
    sign_params = sorted([
        ("folder", folder),
        ("public_id", public_id),
        ("timestamp", str(timestamp)),
    ])
    sign_str = "&".join(f"{k}={v}" for k, v in sign_params) + api_secret
    signature = hashlib.sha1(sign_str.encode()).hexdigest()

    resp = requests.post(
            f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload",
            files={"file": (os.path.basename(file_path), buf, "image/png")},
            data={
                "api_key": api_key,
                "timestamp": timestamp,
                "signature": signature,
                "folder": folder,
                "public_id": public_id,
            },
            verify=False,
        )

    if not resp.ok:
        try:
            err_body = resp.json()
        except Exception:
            err_body = resp.text
        raise RuntimeError(f"Cloudinary HTTP {resp.status_code}: {err_body}")

    return resp.json().get("secure_url")


def save_to_airtable(
    subsidiary_code: str,
    country_label: str,
    mode: str,
    capture_url: str | None,
) -> str | None:
    """Create an Airtable record and return the record ID, or None on failure.

    Table columns: Name, domain, country, period, banner-type, capture
    """
    api_key = _secret("AIRTABLE_API_KEY")
    base_id = _secret("AIRTABLE_BASE_ID")
    table_name = _secret("AIRTABLE_TABLE_NAME", "MemDays")

    if not all([api_key, base_id]):
        return None

    token_hint = f"{api_key[:8]}..." if api_key else "missing"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # Pre-flight: verify the token can read this base/table before writing
    test_url = f"https://api.airtable.com/v0/{base_id}/{requests.utils.quote(table_name)}?maxRecords=1"
    test_resp = requests.get(test_url, headers=headers)
    if not test_resp.ok:
        try:
            err_body = test_resp.json()
        except Exception:
            err_body = test_resp.text
        raise RuntimeError(
            f"Pre-flight check failed (token: {token_hint}, base: {base_id}, table: {table_name!r}) "
            f"→ HTTP {test_resp.status_code}: {err_body}"
        )

    country_name = country_label.split(" (")[0]
    mode_suffix = "pc" if mode == "desktop" else "mo"
    banner_type = f"pre-memberdays-{mode_suffix}"
    period = datetime.now().strftime("%m/%d/%Y")
    record_name = f"{subsidiary_code}-pre-memberdays-{mode_suffix}"

    fields: dict = {
        "Name": record_name,
        "domain": subsidiary_code,
        "country": country_name,
        "period": period,
        "banner-type": banner_type,
    }
    if capture_url:
        fields["capture"] = [{"url": capture_url}]

    post_url = f"https://api.airtable.com/v0/{base_id}/{requests.utils.quote(table_name)}"
    resp = requests.post(post_url, json={"fields": fields}, headers=headers)
    if not resp.ok:
        try:
            err_body = resp.json()
        except Exception:
            err_body = resp.text
        raise RuntimeError(f"HTTP {resp.status_code}: {err_body}")
    return resp.json().get("id")


def page_cleanup(page) -> None:
    """Remove overlays and disable motion before capture."""
    page.evaluate(
        """
        () => {
            const style = document.createElement('style');
            style.innerHTML = `
                [class*="chat"], [id*="chat"], [class*="cookie"], [id*="cookie"],
                .c-pop-toast__container, .c-notification-banner,
                #onetrust-consent-sdk, .onetrust-pc-dark-filter,
                .embeddedServiceHelpButton, .floating-button-portal,
                .l-cookie-teaser, .c-membership-popup {
                    display: none !important;
                    visibility: hidden !important;
                    opacity: 0 !important;
                    pointer-events: none !important;
                }
                *, *::before, *::after {
                    animation-duration: 0s !important;
                    transition-duration: 0s !important;
                    animation-delay: 0s !important;
                    transition-delay: 0s !important;
                }
            `;
            document.head.appendChild(style);
            document.querySelectorAll('video').forEach(v => v.pause());
            window.scrollTo(0, 0);
        }
        """
    )


def is_access_denied_page(page) -> bool:
    """Detect genuine WAF/CDN block pages only.

    Uses inner_text (visible text only) to avoid false-positives from
    script/JSON content that legitimately contains words like 'bot' or 'blocked'.
    Only matches phrases that only ever appear on actual block screens.
    """
    try:
        # inner_text returns only visible rendered text, filters out scripts/styles
        page_text = page.inner_text("body").lower()
    except Exception:
        page_text = ""

    try:
        title = page.title().lower()
    except Exception:
        title = ""

    # Keep markers specific: must only appear on genuine block/error pages
    block_title_markers = [
        "access denied",
        "403 forbidden",
        "error 403",
        "request blocked",
        "attention required",  # Cloudflare block page
    ]
    block_body_markers = [
        "access denied",
        "you don't have permission to access",
        "your request has been blocked",
        "this site is protected by",  # generic WAF message
        "enable cookies and reload",  # often appears on LG block pages
        "ray id",  # Cloudflare block fingerprint
    ]

    if any(m in title for m in block_title_markers):
        return True
    if any(m in page_text for m in block_body_markers):
        return True
    return False


def capture_full_page(url: str, subsidiary_code: str, mode: str) -> str:
    output_dir = "captures"
    os.makedirs(output_dir, exist_ok=True)
    debug_dir = os.path.join(output_dir, "debug")
    os.makedirs(debug_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{subsidiary_code}_{mode}_prememberdays_{timestamp}.png"
    output_path = os.path.join(output_dir, filename)

    is_mobile = mode == "mobile"
    # 1920p desktop / iPhone standard — 2× DPR gives 3840px wide (4K), visually
    # sharp and typically 3–5 MB per page, well under PIL's 178 MP safety limit.
    viewport = {"width": 1920, "height": 1080} if not is_mobile else {"width": 390, "height": 844}
    profiles = [
        {
            "name": "win_en",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "locale": "en-US",
            "timezone": "America/New_York",
            "sec_ch_ua": '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
            "sec_ch_ua_mobile": "?1" if is_mobile else "?0",
            "sec_ch_ua_platform": '"Windows"',
        },
        {
            "name": "mac_en",
            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "locale": "en-GB",
            "timezone": "Europe/London",
            "sec_ch_ua": '"Not A(Brand";v="99", "Google Chrome";v="124", "Chromium";v="124"',
            "sec_ch_ua_mobile": "?1" if is_mobile else "?0",
            "sec_ch_ua_platform": '"macOS"',
        },
        {
            "name": "win_en_v2",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "locale": "en-US",
            "timezone": "America/Chicago",
            "sec_ch_ua": '"Not A(Brand";v="99", "Google Chrome";v="122", "Chromium";v="122"',
            "sec_ch_ua_mobile": "?1" if is_mobile else "?0",
            "sec_ch_ua_platform": '"Windows"',
        },
    ]

    last_error = ""
    access_denied_debugs: list[str] = []

    with sync_playwright() as playwright:
        for profile in profiles:
            browser = playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-extensions",
                    "--start-maximized",
                    "--force-device-scale-factor=2",  # 2× DPR → 3840px wide (4K)
                ],
            )
            context = browser.new_context(
                viewport=viewport,
                device_scale_factor=2,  # Retina/4K quality without excessive file size
                user_agent=profile["user_agent"],
                locale=profile["locale"],
                timezone_id=profile["timezone"],
                extra_http_headers={
                    "Upgrade-Insecure-Requests": "1",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                    "Accept-Language": profile["locale"].replace("-", ",") + ";q=0.9",
                    "Sec-Ch-Ua": profile["sec_ch_ua"],
                    "Sec-Ch-Ua-Mobile": profile["sec_ch_ua_mobile"],
                    "Sec-Ch-Ua-Platform": profile["sec_ch_ua_platform"],
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Sec-Fetch-User": "?1",
                },
            )
            # Stealth: hide webdriver fingerprint
            context.add_init_script(_STEALTH_INIT_SCRIPT)
            page = context.new_page()

            # Block known chat/analytics endpoints that trigger bot detection
            def _block_chat(route):
                u = route.request.url.lower()
                if any(k in u for k in ["genesys", "liveperson", "salesforceliveagent", "adobe-privacy", "chatbot", "proactive-chat"]):
                    route.abort()
                else:
                    route.continue_()
            page.route("**/*", _block_chat)

            try:
                # Mouse jitter before navigation to appear human
                page.mouse.move(random.randint(0, 500), random.randint(0, 300))

                response = page.goto(url, wait_until="domcontentloaded", timeout=120000)
                status_code = response.status if response else None

                # More mouse jitter after page load
                page.mouse.move(random.randint(100, 800), random.randint(100, 600))

                try:
                    accept_btn = page.locator("#onetrust-accept-btn-handler")
                    if accept_btn.is_visible(timeout=5000):
                        accept_btn.click()
                        time.sleep(0.5)
                except Exception:
                    pass

                page_cleanup(page)

                # Wait for all network activity to settle so images are fully loaded
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass  # Proceed even if some requests never settle

                # Force all images to render at crisp full resolution
                page.evaluate("""
                    () => {
                        document.querySelectorAll('img').forEach(img => {
                            img.style.imageRendering = 'auto';
                            img.decoding = 'sync';
                            if (img.loading === 'lazy') {
                                img.loading = 'eager';
                                const src = img.src;
                                img.src = '';
                                img.src = src;
                            }
                        });
                    }
                """)
                time.sleep(0.5)

                if is_access_denied_page(page):
                    debug_base = os.path.join(debug_dir, f"{subsidiary_code}_{mode}_{profile['name']}_{timestamp}")
                    debug_png = f"{debug_base}.png"
                    debug_html = f"{debug_base}.html"
                    page.screenshot(path=debug_png, full_page=True, type="png")
                    with open(debug_html, "w", encoding="utf-8") as fp:
                        fp.write(page.content())
                    access_denied_debugs.append(debug_png)
                    continue

                if status_code and status_code >= 400:
                    raise RuntimeError(
                        f"LG page returned HTTP {status_code} for {url}. "
                        "This subsidiary may not have a prememberdays page."
                    )

                # PNG is lossless; omit quality param (only applies to jpeg)
                page.screenshot(
                    path=output_path,
                    full_page=True,
                    type="png",
                    scale="device",  # honours the 3× device_scale_factor
                )
                return output_path
            except Exception as exc:
                last_error = str(exc)
            finally:
                context.close()
                browser.close()

    if access_denied_debugs:
        raise RuntimeError(
            "LG returned access denied for all retry profiles in this environment. "
            f"Diagnostic screenshots saved under: {debug_dir}"
        )
    if last_error:
        raise RuntimeError(last_error)
    raise RuntimeError("Capture failed for an unknown reason.")


def main() -> None:
    st.set_page_config(page_title="LG Member Days Capture", layout="wide")
    st.title("LG Member Days Capture")

    runtime_status = install_playwright_chromium()
    playwright_ready = bool(runtime_status.get("ready"))

    if playwright_ready:
        st.success("Browser runtime check passed.")
    else:
        st.error(str(runtime_status.get("message", "Playwright runtime not ready.")))
        st.info(
            "If apt update fails due the Yarn repo signature, disable that source and retry:\n"
            "sudo sed -i 's/^deb /# deb /' /etc/apt/sources.list.d/yarn.list\n"
            "sudo apt-get update"
        )
        with st.expander("Diagnostics", expanded=False):
            st.text(str(runtime_status.get("diagnostics", "")))

    options = get_subsidiary_options()
    labels = [label for _, label in options]

    selected_code_init = next(
        code for code, label in options if label == labels[0]
    )

    with st.sidebar:
        st.header("Capture Settings")
        selected_label = st.selectbox("Subsidiary", options=labels, index=0)
        mode = st.selectbox("Mode", options=["desktop", "mobile"], index=0)

        # Resolve default URL whenever the subsidiary or mode changes
        selected_code = next(code for code, label in options if label == selected_label)
        default_url, target_status = resolve_target_url(selected_code)
        url_key = f"target_url_{selected_code}_{mode}"
        if url_key not in st.session_state:
            st.session_state[url_key] = default_url

        target_url = st.text_input(
            "Target URL",
            value=st.session_state[url_key],
            key=f"url_input_{selected_code}_{mode}",
            help="Auto-filled from the selected subsidiary. Edit and press Enter to save.",
        )
        st.session_state[url_key] = target_url

        if target_status == 404 and target_url == default_url:
            st.warning(
                "This subsidiary currently returns 404 for prememberdays. "
                "Edit the URL above or capture may fail."
            )

        capture = st.button(
            "Capture Full Page",
            type="primary",
            use_container_width=True,
            disabled=not playwright_ready,
        )

    selected_code = next(code for code, label in options if label == selected_label)

    if capture:
        status = st.status("Starting capture...", expanded=True)
        with status:
            st.write("Launching browser...")
            try:
                output_path = capture_full_page(target_url, selected_code, mode)
                status.update(label="Capture complete", state="complete")
                st.session_state["last_output_path"] = output_path
                st.session_state["last_subsidiary_code"] = selected_code
                st.session_state["last_selected_label"] = selected_label
                st.session_state["last_mode"] = mode
                st.session_state["airtable_status"] = None  # reset previous upload status
            except Exception as exc:
                status.update(label="Capture failed", state="error")
                st.error(f"Capture failed: {exc}")
                return

    # Show results UI whenever a captured file exists in session state
    output_path = st.session_state.get("last_output_path")
    if output_path and os.path.exists(output_path):
        import struct
        with open(output_path, "rb") as _f:
            _raw = _f.read()
        _w = struct.unpack(">I", _raw[16:20])[0]
        _h = struct.unpack(">I", _raw[20:24])[0]
        _mb = len(_raw) / 1024 / 1024

        _airtable_configured = bool(_secret("AIRTABLE_API_KEY")) and bool(_secret("AIRTABLE_BASE_ID"))
        st.markdown(
            """
            <style>
            [data-testid="stDownloadButton"] button,
            div[data-testid="stButton"] button.airtable-btn {
                background-color: #FF4B4B !important;
                color: white !important;
                border: none !important;
            }
            [data-testid="stDownloadButton"] button:hover {
                background-color: #cc3b3b !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        col_dl, col_at = st.columns(2)
        with col_dl:
            with open(output_path, "rb") as image_file:
                st.download_button(
                    label=f"⬇️ Download PNG ({_mb:.1f} MB)",
                    data=image_file.read(),
                    file_name=os.path.basename(output_path),
                    mime="image/png",
                    use_container_width=True,
                )
        with col_at:
            upload_clicked = st.button(
                "📋 Upload to Airtable",
                use_container_width=True,
                disabled=not _airtable_configured,
                help="Configure AIRTABLE_API_KEY and AIRTABLE_BASE_ID in Streamlit secrets to enable.",
            )

        if upload_clicked:
            _sub = st.session_state.get("last_subsidiary_code", selected_code)
            _label = st.session_state.get("last_selected_label", selected_label)
            _m = st.session_state.get("last_mode", mode)
            with st.spinner("Uploading…"):
                _capture_url = None
                if all([_secret("CLOUDINARY_CLOUD_NAME"), _secret("CLOUDINARY_API_KEY"), _secret("CLOUDINARY_API_SECRET")]):
                    try:
                        _capture_url = upload_to_cloudinary(output_path, _sub, _m)
                        st.caption(f"📤 Cloudinary: {_capture_url}")
                    except Exception as _e:
                        st.warning(f"Cloudinary upload failed: {_e}")
                try:
                    _record_id = save_to_airtable(_sub, _label, _m, _capture_url)
                    st.session_state["airtable_status"] = ("success", f"✅ Saved to Airtable (record: {_record_id})")
                except Exception as _e:
                    _err_detail = str(_e)
                    if hasattr(_e, "response") and _e.response is not None:
                        try:
                            _err_detail = _e.response.json()
                        except Exception:
                            _err_detail = _e.response.text
                    st.session_state["airtable_status"] = ("error", f"Airtable upload failed: {_err_detail}")

        # Show persistent upload status
        _at_status = st.session_state.get("airtable_status")
        if _at_status:
            if _at_status[0] == "success":
                st.success(_at_status[1])
            else:
                st.error(_at_status[1])

        st.subheader("Screenshot")
        st.caption(f"Resolution: **{_w:,} × {_h:,} px** &nbsp;|&nbsp; File size: **{_mb:.1f} MB**")
        st.info("ℹ️ The preview below is compressed by Streamlit. Download for full-quality image.")
        st.image(output_path, use_container_width=True)


if __name__ == "__main__":
    main()