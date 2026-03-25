#!/usr/bin/env node

const { Command } = require('commander');
const { spawn } = require('child_process');
const path = require('path');
const pkg = require('../package.json');

const SCRIPTS = path.join(__dirname, '..', 'scripts');

function run(cmd, args) {
  const proc = spawn(cmd, args, { stdio: 'inherit', cwd: process.cwd() });
  proc.on('error', (err) => {
    console.error(`Failed to execute: ${err.message}`);
    process.exit(1);
  });
  proc.on('close', (code) => process.exit(code ?? 1));
}

function bash(script, args) {
  run('bash', [path.join(SCRIPTS, script), ...args]);
}

function python(script, args) {
  run('python3', [path.join(SCRIPTS, script), ...args]);
}

const program = new Command();

program
  .name('fameclaw')
  .description('FameClaw \uD83E\uDD9E \u2014 YouTube Creator Outreach')
  .version(pkg.version);

// ── scan ──
program
  .command('scan')
  .description('Scan a brand URL to build an audience profile')
  .requiredOption('--url <url>', 'URL to scan')
  .option('--output <file>', 'Output file', 'scan.json')
  .action((opts) => {
    bash('onboard.sh', ['--brand', '', '--url', opts.url, '--output', opts.output]);
  });

// ── prospect ──
program
  .command('prospect')
  .description('Find creators matching queries (YouTube or TikTok)')
  .option('-p, --platform <platform>', 'Platform: youtube (default), tiktok, x')
  .option('--queries <queries...>', 'Search queries (YouTube)')
  .option('--hashtags <hashtags...>', 'Hashtags to scrape (TikTok)')
  .option('--handles <handles...>', 'X handles to extract')
  .option('--target <n>', 'Target number of creators', '100')
  .option('--output <file>', 'Output CSV file')
  .option('--max-subs <n>', 'Max subscriber count (YouTube)', '100000')
  .option('--max-followers <n>', 'Max follower count (TikTok)', '0')
  .option('--batch-size <n>', 'Batch size (YouTube)', '200')
  .option('--scrolls <n>', 'Scrolls per hashtag page (TikTok)', '3')
  .option('--config <file>', 'Config JSON file (YouTube)')
  .action((opts) => {
    const platform = opts.platform || 'youtube';

    if (platform === 'x') {
      if (!opts.handles || opts.handles.length === 0) {
        console.error('Error: --handles is required for X prospecting');
        process.exit(1);
      }
      const output = opts.output || 'x_creators.csv';
      const handles = opts.handles;
      let i = 0;
      function nextHandle() {
        if (i >= handles.length) {
          console.log(`\nDone! Extracted ${handles.length} X profiles to ${output}`);
          return;
        }
        const handle = handles[i].replace(/^@/, '');
        console.log(`\n[${i + 1}/${handles.length}] Extracting @${handle}...`);
        const proc = spawn('bash', [path.join(SCRIPTS, 'extract_x.sh'), handle, output], {
          stdio: 'inherit',
          cwd: process.cwd(),
        });
        proc.on('close', (code) => {
          i++;
          if (i < handles.length) {
            // Rate limit: 1.5s between requests
            setTimeout(nextHandle, 1500);
          } else {
            nextHandle();
          }
        });
        proc.on('error', (err) => {
          console.error(`Failed: ${err.message}`);
          process.exit(1);
        });
      }
      nextHandle();
      return;
    }

    if (platform === 'tiktok') {
      if (!opts.hashtags || opts.hashtags.length === 0) {
        console.error('Error: --hashtags is required for TikTok prospecting');
        process.exit(1);
      }
      const output = opts.output || 'tiktok_creators.csv';
      const args = [
        '--hashtags', ...opts.hashtags,
        '--target', opts.target,
        '--output', output,
        '--scrolls', opts.scrolls,
      ];
      if (opts.maxFollowers && opts.maxFollowers !== '0') {
        args.push('--max-followers', opts.maxFollowers);
      }
      bash('prospect_tiktok.sh', args);
    } else {
      if (opts.config) {
        bash('prospect.sh', ['--config', opts.config]);
      } else {
        if (!opts.queries || opts.queries.length === 0) {
          console.error('Error: --queries or --config is required');
          process.exit(1);
        }
        const output = opts.output || 'channels.csv';
        bash('prospect.sh', [
          '--queries', ...opts.queries,
          '--target', opts.target,
          '--output', output,
          '--max-subs', opts.maxSubs,
          '--batch-size', opts.batchSize,
        ]);
      }
    }
  });

// ── score ──
program
  .command('score')
  .description('Score channels against an audience profile')
  .requiredOption('--csv <file>', 'Input CSV of channels')
  .requiredOption('--profile <file>', 'Audience profile JSON')
  .option('--output <file>', 'Output scored CSV', 'scored.csv')
  .action((opts) => {
    python('score_channels.py', ['--csv', opts.csv, '--profile', opts.profile, '--output', opts.output]);
  });

// ── Platform detection helper ──
function detectPlatform(url) {
  if (/tiktok\.com/i.test(url)) return 'tiktok';
  if (/(?:^|\/\/)(x|twitter)\.com/i.test(url)) return 'x';
  if (/youtube\.com|youtu\.be/i.test(url)) return 'youtube';
  return null;
}

function resolvePlatform(url, explicit) {
  if (explicit) return explicit;
  const detected = detectPlatform(url);
  if (detected) return detected;
  return 'youtube'; // default
}

// ── extract ──
program
  .command('extract <url>')
  .description('Extract data from a creator profile')
  .option('-p, --platform <platform>', 'Platform: youtube, tiktok (auto-detected from URL)')
  .option('--output <file>', 'Output CSV file')
  .action((url, opts) => {
    const platform = resolvePlatform(url, opts.platform);
    const defaultOutput = platform === 'tiktok' ? 'tiktok_data.csv' : platform === 'x' ? 'x_data.csv' : 'output.csv';
    const output = opts.output || defaultOutput;
    if (platform === 'x') {
      bash('extract_x.sh', [url, output]);
    } else if (platform === 'tiktok') {
      bash('extract_tiktok.sh', [url, output]);
    } else {
      bash('extract_channel_data.sh', [url, output]);
    }
  });

// ── email ──
program
  .command('email <url>')
  .description('Extract email from a creator profile')
  .option('-p, --platform <platform>', 'Platform: youtube, tiktok (auto-detected from URL)')
  .action((url, opts) => {
    const platform = resolvePlatform(url, opts.platform);
    if (platform === 'x') {
      bash('extract_x.sh', [url]);
    } else if (platform === 'tiktok') {
      bash('extract_tiktok.sh', [url]);
    } else {
      bash('extract_email.sh', [url]);
    }
  });

// ── related ──
program
  .command('related <url>')
  .description('Find related channels/creators')
  .option('-p, --platform <platform>', 'Platform: youtube (tiktok coming soon)')
  .option('--count <n>', 'Number of related channels', '20')
  .action((url, opts) => {
    const platform = resolvePlatform(url, opts.platform);
    if (platform === 'tiktok') {
      console.error('TikTok related discovery coming soon. Use --platform youtube for now.');
      process.exit(1);
    }
    bash('find_related_channels.sh', [url, opts.count]);
  });

// ── outreach ──
const outreach = program
  .command('outreach')
  .description('Manage outreach campaigns');

outreach
  .command('send')
  .description('Send outreach emails')
  .requiredOption('--csv <file>', 'Scored CSV file')
  .requiredOption('--config <file>', 'Outreach config JSON')
  .option('--dry-run', 'Preview without sending')
  .action((opts) => {
    const args = ['send', '--csv', opts.csv, '--config', opts.config];
    if (opts.dryRun) args.push('--dry-run');
    python('outreach.py', args);
  });

outreach
  .command('check-replies')
  .description('Check for replies to outreach emails')
  .requiredOption('--config <file>', 'Outreach config JSON')
  .action((opts) => {
    python('outreach.py', ['check-replies', '--config', opts.config]);
  });

outreach
  .command('followup')
  .description('Send follow-up emails')
  .requiredOption('--config <file>', 'Outreach config JSON')
  .option('--dry-run', 'Preview without sending')
  .action((opts) => {
    const args = ['followup', '--config', opts.config];
    if (opts.dryRun) args.push('--dry-run');
    python('outreach.py', args);
  });

outreach
  .command('status')
  .description('Show outreach campaign status')
  .requiredOption('--config <file>', 'Outreach config JSON')
  .action((opts) => {
    python('outreach.py', ['status', '--config', opts.config]);
  });

// ── negotiate ──
const negotiate = program
  .command('negotiate')
  .description('Manage negotiations with creators');

negotiate
  .command('check')
  .description('Check negotiation status')
  .requiredOption('--config <file>', 'Outreach config JSON')
  .option('--dry-run', 'Preview without acting')
  .action((opts) => {
    const args = ['check', '--config', opts.config];
    if (opts.dryRun) args.push('--dry-run');
    python('negotiate.py', args);
  });

negotiate
  .command('status')
  .description('Show negotiation status')
  .requiredOption('--config <file>', 'Outreach config JSON')
  .action((opts) => {
    python('negotiate.py', ['status', '--config', opts.config]);
  });

negotiate
  .command('set-config')
  .description('Set a negotiation config value')
  .requiredOption('--config <file>', 'Outreach config JSON')
  .requiredOption('--key <key>', 'Config key')
  .requiredOption('--value <value>', 'Config value')
  .action((opts) => {
    python('negotiate.py', ['set-config', '--config', opts.config, '--key', opts.key, '--value', opts.value]);
  });

// ── enrich ──
program
  .command('enrich <csv-file>')
  .description('Enrich a CSV with cross-platform social data (X followers, TikTok stats)')
  .option('--platforms <platforms>', 'Comma-separated platforms: x,tiktok', 'x,tiktok')
  .option('--output <file>', 'Output CSV file')
  .action((csvFile, opts) => {
    const args = [csvFile];
    if (opts.output) args.push(opts.output);
    args.push('--platforms', opts.platforms);
    bash('enrich_socials.sh', args);
  });

// ── gmail ──
const gmail = program
  .command('gmail')
  .description('Gmail authentication setup');

gmail
  .command('setup')
  .description('Set up Gmail OAuth credentials')
  .action(() => {
    bash('gmail_auth.sh', ['setup']);
  });

gmail
  .command('test')
  .description('Test Gmail connection')
  .action(() => {
    bash('gmail_auth.sh', ['test']);
  });

program.parse();
