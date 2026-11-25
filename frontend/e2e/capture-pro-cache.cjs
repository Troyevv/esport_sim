// Read the published, anonymous replay. Only save match data served for this viewer.
const {chromium} = require('@playwright/test');
const fs = require('node:fs/promises');
const path = require('node:path');
const {gzipSync} = require('node:zlib');
const {createHash} = require('node:crypto');

async function main() {
  const directory = process.argv[2];
  const url = 'https://cs2replays.com/?replay=M7NNAFXCRBwL';
  await fs.mkdir(directory, {recursive:true});
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    const files = [];
    const reads = [];
    page.on('response', response => {
      const target = new URL(response.url());
      if (!response.ok() || !['xhr','fetch'].includes(response.request().resourceType())) return;
      const source = target.origin + target.pathname;
      // This page also loads anonymous analytics. Only consider first-party
      // replay data and require actual round/player fields before publishing.
      if (target.hostname !== 'cs2replays.com' && !target.hostname.endsWith('.cs2replays.com')) return;
      reads.push((async () => {
        const bytes = await response.body();
        console.log(response.status(), source, bytes.length);
        if (bytes.length < 1000) return;
        let data;
        try { data=JSON.parse(bytes); } catch { return; }
        const sample=JSON.stringify(data).slice(0,90000);
        if (!/round|player/i.test(sample) || !/tick|frame/i.test(sample)) return;
        const hash=createHash('sha256').update(bytes).digest('hex');
        const name='cache-'+hash.slice(0,14)+'.json.gz';
        await fs.writeFile(path.join(directory,name),gzipSync(bytes));
        files.push({source,name,sha256:hash});
      })().catch(error=>console.log(source,error.message)));
    });
    await page.goto(url,{waitUntil:'domcontentloaded',timeout:60000});
    await page.waitForFunction(()=>/Twistzz|MaSvAl/i.test(document.body.innerText),{},{timeout:45000}).catch(()=>{});
    await page.waitForLoadState('networkidle',{timeout:12000}).catch(()=>{});
    await Promise.all(reads);
    await page.screenshot({path:path.join(directory,'cache-view.png')});
    await fs.writeFile(path.join(directory,'source.json'),JSON.stringify({url,files},null,2));
    if (!files.length) throw new Error('No public round payload received from the replay viewer');
  } finally { await browser.close(); }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
