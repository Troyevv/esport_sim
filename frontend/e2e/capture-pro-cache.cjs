// Retrieve the exact published rounds of the FISSURE Playground 3 Cache decider.
const {chromium} = require('@playwright/test');
const fs = require('node:fs/promises');
const path = require('node:path');
const {gzipSync} = require('node:zlib');
const {createHash} = require('node:crypto');

async function main() {
  const directory = process.argv[2];
  const share = 'M7NNAFXCRBwL';
  const url = 'https://cs2replays.com/?replay=' + share;
  const base = new URL('/api/replays/' + share, url);
  await fs.mkdir(directory, {recursive: true});
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.goto(url, {waitUntil: 'domcontentloaded', timeout: 60000});
    const response = await page.request.get(base.href);
    if (!response.ok()) throw new Error('Missing replay manifest');
    const meta = await response.json();
    if (meta.mapName !== 'de_cache' || !meta.sources.some(s => s.providerMatchId === '2397607')) {
      throw new Error('Unexpected map or match in public replay');
    }
    const files = [];
    for (const round of meta.rounds.filter(r => r.endTick > r.startTick)) {
      const source = base.href + '/rounds/' + round.round;
      const res = await page.request.get(source);
      if (!res.ok()) throw new Error('Missing playing round ' + round.round);
      const bytes = await res.body();
      if (bytes.length < 1000) throw new Error('Empty round ' + round.round);
      const hash = createHash('sha256').update(bytes).digest('hex');
      const name = 'round-' + round.round + '.gz';
      await fs.writeFile(path.join(directory, name), gzipSync(bytes));
      files.push({source, name, sha256:hash, bytes:bytes.length, type:res.headers()['content-type']});
      if (files.length === 1) console.log('Round prefix (hex)', bytes.subarray(0,64).toString('hex'));
      await res.dispose();
    }
    if (files.length !== 35) throw new Error('Unexpected number of nonempty rounds');
    await page.screenshot({path:path.join(directory, 'cache-view.png')});
    await fs.writeFile(path.join(directory, 'source.json'), JSON.stringify({url, meta, files}, null, 2));
  } finally { await browser.close(); }
}
main().catch(error => {console.error(error); process.exitCode = 1;});
