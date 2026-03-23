const { chromium } = require("playwright");

// Accepts: --hashtags tag1 tag2 --scrolls 3 --output handles.txt
// Outputs JSON lines to stdout, progress to stderr

(async () => {
  const args = process.argv.slice(2);
  let hashtags = [];
  let scrolls = 3;
  let output = null;

  // Parse args
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--hashtags") {
      i++;
      while (i < args.length && !args[i].startsWith("--")) {
        hashtags.push(args[i]);
        i++;
      }
      i--;
    } else if (args[i] === "--scrolls") {
      scrolls = parseInt(args[++i]);
    } else if (args[i] === "--output") {
      output = args[++i];
    }
  }

  if (hashtags.length === 0) {
    console.error("Usage: node prospect_tiktok_worker.js --hashtags tag1 tag2 [--scrolls 3] [--output file.txt]");
    process.exit(1);
  }

  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    viewport: { width: 1920, height: 1080 },
    locale: "en-US",
  });

  const allCreators = new Map();

  for (const tag of hashtags) {
    const page = await ctx.newPage();
    console.error(`Scraping #${tag}...`);

    await page.goto(`https://www.tiktok.com/tag/${tag}?lang=en`, {
      waitUntil: "domcontentloaded",
      timeout: 30000,
    });
    await page.waitForTimeout(5000);

    // Scroll to load more content
    for (let i = 0; i < scrolls; i++) {
      await page.evaluate(() => window.scrollBy(0, 2000));
      await page.waitForTimeout(2000);
    }

    const data = await page.evaluate((currentTag) => {
      const creators = {};
      // Get tag stats
      const headerMatch = document.body.innerText.match(new RegExp("#" + currentTag + "\\n([\\d.]+[KMB]?\\s*posts?)", "i"));
      const tagStats = headerMatch ? headerMatch[1].trim() : "";

      // Collect creator handles from profile links
      document.querySelectorAll('a[href*="/@"]').forEach((a) => {
        const m = a.href.match(/@([a-zA-Z0-9_.]+)/);
        if (m && m[1].length > 1) {
          const handle = m[1];
          if (!creators[handle]) {
            creators[handle] = { videos: 0, tags: [currentTag] };
          }
        }
      });

      // Count videos per creator
      document.querySelectorAll('a[href*="/video/"]').forEach((a) => {
        const m = a.href.match(/@([a-zA-Z0-9_.]+)\/video/);
        if (m && creators[m[1]]) {
          creators[m[1]].videos++;
        }
      });

      return { creators, tagStats };
    }, tag);

    console.error(`  #${tag}: ${data.tagStats || "?"} — ${Object.keys(data.creators).length} creators`);

    for (const [handle, info] of Object.entries(data.creators)) {
      if (allCreators.has(handle)) {
        const existing = allCreators.get(handle);
        existing.videos += info.videos;
        existing.tags = [...new Set([...existing.tags, ...info.tags])];
      } else {
        allCreators.set(handle, info);
      }
    }

    await page.close();
  }

  await browser.close();

  // Output unique handles sorted by video count (most active first)
  const sorted = [...allCreators.entries()]
    .filter(([h, _]) => h.length > 1)
    .sort((a, b) => b[1].videos - a[1].videos);

  // Output as JSON lines to stdout (one per line)
  const lines = sorted.map(([handle, info]) =>
    JSON.stringify({ handle, videos: info.videos, tags: info.tags })
  );

  if (output) {
    require("fs").writeFileSync(output, lines.join("\n") + "\n");
    console.error(`\nWrote ${sorted.length} creators to ${output}`);
  } else {
    lines.forEach(l => console.log(l));
  }

  console.error(`\nTotal unique creators: ${sorted.length}`);
})();
