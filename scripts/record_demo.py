"""Record the required interactive dashboard demonstration to demo.webm."""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"demo.webm"
TMP=ROOT/"work"/"browser-video"

async def main():
    TMP.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        context=await browser.new_context(viewport={"width":1440,"height":1000},record_video_dir=str(TMP),record_video_size={"width":1440,"height":1000})
        page=await context.new_page()
        errors=[]
        page.on("pageerror",lambda exc:errors.append(str(exc)))
        await page.goto("http://127.0.0.1:8765",wait_until="networkidle",timeout=60000)
        await page.wait_for_timeout(1800)
        await page.get_by_role("button",name="Test changed field names and units").click()
        await page.wait_for_timeout(1800)
        await page.get_by_role("tab",name="Agent messages").click()
        await page.wait_for_timeout(2200)
        await page.get_by_role("tab",name="JSON report").click()
        await page.wait_for_timeout(1600)
        await page.get_by_role("tab",name="Agent messages").click()
        await page.wait_for_timeout(1500)
        # Scroll the main page to show topology, multi-metric charts, and controls.
        await page.mouse.wheel(0,900)
        await page.wait_for_timeout(2200)
        await context.close()
        await browser.close()
    videos=list(TMP.glob("*.webm"))
    if not videos: raise RuntimeError("Playwright did not create a video recording")
    videos[-1].replace(OUT)
    if errors: raise RuntimeError("Browser errors: "+"; ".join(errors))
    print(f"Recorded {OUT}")

if __name__=="__main__": asyncio.run(main())
