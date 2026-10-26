"""Browser smoke test for the map page (optional; needs Playwright).

    pip install playwright && python -m playwright install chromium
    python -m http.server -d web 8765            # in another terminal
    python tools/check_map.py http://localhost:8765/ out/

Loads the page at phone size, checks every data layer loads with no console
errors, taps an area tab and the suburb borders switch, flips the time between
Monday 8am and Sunday 3am, runs the drop-off finder near The Tivoli, builds a
report message, opens a popup, and saves screenshots (light and dark) into the
output folder.
"""
import asyncio, sys
from pathlib import Path
from playwright.async_api import async_playwright
URL = sys.argv[1]; OUT = sys.argv[2]
Path(OUT).mkdir(parents=True, exist_ok=True)
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        pg = await ctx.new_page()
        errs = []
        pg.on("console", lambda m: errs.append(f"{m.type}: {m.text}") if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
        await pg.goto(URL, wait_until="networkidle", timeout=90000)
        await pg.wait_for_selector("body[data-ready='1']", timeout=60000)
        await pg.wait_for_timeout(2500)
        counts = await pg.evaluate("() => Object.fromEntries(Object.entries(window.__dropoff.DATA).map(([k,v]) => [k, v.features.length]))")
        cams = await pg.evaluate("() => document.querySelectorAll('.cam-pin').length")
        print("counts", counts, "camera pins", cams)
        await pg.screenshot(path=f"{OUT}/a_default.png")
        # area tabs: tap Valley, the map should frame it and light its tab
        tabs = await pg.evaluate("() => [...document.querySelectorAll('#areas button')].map(b => b.textContent)")
        await pg.click("#areas button[data-area='valley']")
        await pg.wait_for_timeout(2000)
        area = await pg.evaluate("""() => { const m = window.__dropoff.map, c = m.getCenter();
            const names = (ids) => m.queryRenderedFeatures({layers: ids}).map(f => f.properties.text || f.properties.name);
            return {tabs_lit: [...document.querySelectorAll('#areas [aria-current="true"]')].map(b => b.textContent),
                    centre_in: window.__dropoff.areaAt(c.lng, c.lat), link: location.hash, zoom: +m.getZoom().toFixed(2),
                    suburb_names: names(['area-labels']), landmarks: names(['landmarks'])}; }""")
        print("tabs", tabs, "after tapping Valley", area)
        await pg.click("#borders-toggle")
        await pg.wait_for_timeout(800)
        print("suburb borders:", await pg.evaluate("() => window.__dropoff.map.getLayoutProperty('suburb-borders', 'visibility')"))
        await pg.screenshot(path=f"{OUT}/a2_valley_borders.png")
        await pg.click("#borders-toggle")
        # zoom into the Valley to see sign zones
        await pg.evaluate("() => window.__dropoff.map.jumpTo({center:[153.0345,-27.4565], zoom:16.6})")
        await pg.wait_for_timeout(2500)
        await pg.screenshot(path=f"{OUT}/b_valley_z16.png")
        # time-awareness: Mon 8am vs Sun 3am
        res = {}
        for label, t in (("mon8am", {"day":0,"minute":480}), ("sun3am", {"day":6,"minute":180})):
            res[label] = await pg.evaluate("""(t) => { window.__dropoff.setChosen(t);
                const D = window.__dropoff.DATA; const on = (n) => D[n].features.filter(f => f.properties.on !== false).length;
                return {clearways_on: on('clearways'), red_on: on('red'), green_on: on('green')}; }""", t)
        print("time", res)
        await pg.evaluate("() => window.__dropoff.setChosen({day:0, minute:480})")
        await pg.evaluate("() => window.__dropoff.map.jumpTo({center:[153.0275,-27.4655], zoom:15.5})")
        await pg.wait_for_timeout(2000)
        await pg.screenshot(path=f"{OUT}/c_mon8am_cbd.png")
        await pg.evaluate("() => window.__dropoff.setChosen(null)")
        # finder near The Tivoli, Costin St
        await pg.click("#find-btn")
        await pg.evaluate("() => window.__dropoff.setDestination([153.03146, -27.45229], 'The Tivoli')")
        await pg.wait_for_timeout(1500)
        print("finder:", await pg.evaluate("() => document.getElementById('find-results').innerText.replace(/\\n/g,' | ')"))
        print("finder note:", await pg.evaluate("() => document.getElementById('find-note').innerText"))
        await pg.screenshot(path=f"{OUT}/d_finder.png")
        await pg.click("#find-sheet .close")
        # report text
        await pg.click("#report-btn")
        await pg.evaluate("() => window.__dropoff.map.jumpTo({center:[153.0362,-27.4574], zoom:18})")
        await pg.wait_for_timeout(800)
        print("report text:\n" + await pg.evaluate("() => window.__dropoff.reportText()"))
        await pg.screenshot(path=f"{OUT}/e_report.png")
        await pg.click("#report-sheet .close")
        # popup on a red feature: find a rendered red feature and click its pixel
        pt = await pg.evaluate("""() => { const m = window.__dropoff.map; m.jumpTo({center:[153.0345,-27.4565], zoom:17.5});
            return null; }""")
        await pg.wait_for_timeout(1500)
        pt = await pg.evaluate("""() => { const m = window.__dropoff.map;
            const f = m.queryRenderedFeatures({layers:['red','nogo-red'].filter(id => m.getLayer(id) && m.getLayoutProperty(id,'visibility') !== 'none')}).find(f => f.properties.src === 'sign');
            if (!f) return null; const c = f.geometry.coordinates[Math.floor(f.geometry.coordinates.length/2)];
            const p = m.project(c); return [p.x, p.y]; }""")
        if pt:
            await pg.mouse.click(pt[0], pt[1]); await pg.wait_for_timeout(700)
            print("popup:", await pg.evaluate("() => document.querySelector('.maplibregl-popup-content')?.innerText.replace(/\\n/g,' | ')"))
            await pg.screenshot(path=f"{OUT}/f_popup.png")
        print("errors:", [e for e in errs if 'GL Driver' not in e][:8])
        await ctx.close()
        # dark mode
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, color_scheme="dark")
        pg = await ctx.new_page()
        await pg.goto(URL, wait_until="networkidle", timeout=90000)
        await pg.wait_for_selector("body[data-ready='1']", timeout=60000)
        await pg.wait_for_timeout(2500)
        await pg.screenshot(path=f"{OUT}/g_dark.png")
        await b.close()
asyncio.run(main())
