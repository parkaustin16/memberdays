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

    cloud_name = _secret("CLOUDINARY_CLOUD_NAME")
    api_key = _secret("CLOUDINARY_API_KEY")
    api_secret = _secret("CLOUDINARY_API_SECRET")

    if not all([cloud_name, api_key, api_secret]):
        return None

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

    with open(file_path, "rb") as f:
        resp = requests.post(
            f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload",
            files={"file": f},
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


def capture_full_page(url: str, subsidiary_code: str, mode: str) -> str:
    """Capture a full-page screenshot of an LG.com Member Days page and return the saved path."""

    if mode == "mobile":
        viewport = {"width": 390, "height": 844}
        device_scale_factor = 2
        is_mobile = True
        user_agent = (
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36"
        )
        sec_ch_ua_mobile = "?1"
        sec_ch_ua_platform = '"Android"'
    else:
        viewport = {"width": 1920, "height": 1080}
        device_scale_factor = 1
        is_mobile = False
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )
        sec_ch_ua_mobile = "?0"
        sec_ch_ua_platform = '"Windows"'

    os.makedirs("captures", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{subsidiary_code}_{mode}_{timestamp}.png"
    output_path = os.path.join("captures", filename)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-gpu",
                "--disable-extensions",
                "--ignore-certificate-errors",
                "--start-maximized",
            ],
        )

        context = browser.new_context(
            viewport=viewport,
            device_scale_factor=device_scale_factor,
            is_mobile=is_mobile,
            user_agent=user_agent,
            locale="en-US",
            timezone_id="America/New_York",
            ignore_https_errors=True,
            extra_http_headers={
                "Upgrade-Insecure-Requests": "1",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Sec-Ch-Ua": '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
                "Sec-Ch-Ua-Mobile": sec_ch_ua_mobile,
                "Sec-Ch-Ua-Platform": sec_ch_ua_platform,
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            },
        )
        context.add_init_script(f"({_STEALTH_INIT_SCRIPT})()")

        page = context.new_page()

        # ── Block chat / tracking requests that trigger bot-detection ─────────
        def _block_unwanted(route):
            _u = route.request.url.lower()
            _blocked = ["genesys", "liveperson", "salesforceliveagent", "adobe-privacy", "chatbot", "proactive-chat"]
            if any(k in _u for k in _blocked):
                route.abort()
            else:
                route.continue_()

        page.route("**/*", _block_unwanted)

        # ── Human-like mouse jitter before navigation ─────────────────────────
        page.mouse.move(random.randint(0, 500), random.randint(0, 400))

        page.goto(url, wait_until="domcontentloaded", timeout=90_000)

        # Additional jitter post-load
        page.mouse.move(random.randint(100, 800), random.randint(100, 600))

        # Let the page settle
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception:
            page.wait_for_timeout(3_000)

        # ── Dismiss OneTrust cookie / consent banner ──────────────────────────
        for selector in [
            "#onetrust-accept-btn-handler",
            "#accept-recommended-btn-handler",
            "button.onetrust-accept-btn-handler",
        ]:
            try:
                btn = page.locator(selector)
                btn.wait_for(state="visible", timeout=4_000)
                btn.click()
                page.wait_for_timeout(800)
                break
            except Exception:
                continue

        # ── Scroll through to trigger lazy-loaded images/components ──────────
        total_height: int = page.evaluate("document.body.scrollHeight")
        step = viewport["height"]
        pos = 0
        while pos < total_height:
            pos += step
            page.evaluate(f"window.scrollTo(0, {pos})")
            page.wait_for_timeout(150)
            total_height = page.evaluate("document.body.scrollHeight")

        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(500)

        # ── CSS cleanup: remove overlays, disable transitions ─────────────────
        page.evaluate("""
            () => {
                const style = document.createElement('style');
                style.innerHTML = `
                    [class*="chat"], [id*="chat"], [class*="proactive"],
                    .alk-container, #genesys-chat, .genesys-messenger,
                    .floating-button-portal, #WAButton, .embeddedServiceHelpButton,
                    .c-pop-toast__container, .onetrust-pc-dark-filter, #onetrust-consent-sdk,
                    .c-membership-popup,
                    [class*="cloud-shoplive"], [class*="csl-"], [class*="svelte-"],
                    .l-cookie-teaser, .c-cookie-settings, .LiveMiniPreview,
                    .c-notification-banner, .open-button,
                    [id*="launcher"], [class*="helpdesk"]
                    { display: none !important; visibility: hidden !important;
                      opacity: 0 !important; pointer-events: none !important; }
                    *, *::before, *::after {
                        transition-duration: 0s !important;
                        animation-duration: 0s !important;
                        transition-delay: 0s !important;
                        animation-delay: 0s !important;
                    }
                `;
                document.head.appendChild(style);
                ['onetrust-banner-sdk', 'onetrust-pc-dark-filter'].forEach(id => {
                    const el = document.getElementById(id);
                    if (el) el.remove();
                });
                document.querySelectorAll('video').forEach(v => v.pause());
            }
        """)
        page.wait_for_timeout(300)

        # ── Full-page screenshot ──────────────────────────────────────────────
        page.screenshot(path=output_path, full_page=True, type="png")

        context.close()
        browser.close()

    return output_path


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