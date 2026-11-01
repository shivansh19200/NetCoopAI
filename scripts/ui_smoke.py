import asyncio
import sys
from playwright.async_api import async_playwright

async def main():
    if hasattr(sys.stdout,"reconfigure"): sys.stdout.reconfigure(encoding="utf-8",errors="replace")
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True); page=await browser.new_page(viewport={"width":1440,"height":1000})
        errors=[]; page.on("pageerror",lambda error:errors.append(str(error)))
        await page.goto("http://127.0.0.1:8765",wait_until="domcontentloaded",timeout=30000)
        await page.wait_for_timeout(10000)
        print("TITLE",await page.title()); print("TEXT",(await page.locator("body").inner_text())[:5000]); print("ERRORS",errors)
        await page.screenshot(path="work/ui-smoke.png",full_page=True)
        await page.locator('[data-testid="stMain"]').evaluate("e => e.scrollTop = 1200")
        await page.wait_for_timeout(1000)
        await page.screenshot(path="work/ui-smoke-topology.png",full_page=False); await browser.close()
if __name__=="__main__": asyncio.run(main())
