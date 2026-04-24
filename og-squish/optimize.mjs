#!/usr/bin/env node
import sharp from 'sharp';
import { readdir, readFile, writeFile, stat } from 'node:fs/promises';
import { join, extname, resolve } from 'node:path';

const OG_WIDTH = 1200;
const OG_HEIGHT = 630;
const TARGET_KB = 300;

const args = process.argv.slice(2);
const dir = resolve(args[0] || '.');
const dryRun = args.includes('--dry');

const fmtKB = (bytes) => `${(bytes / 1024).toFixed(0)} KB`;

async function optimizeOne(filePath) {
  const before = (await stat(filePath)).size;
  const ext = extname(filePath).toLowerCase();

  const input = await readFile(filePath);
  const pipeline = sharp(input).resize(OG_WIDTH, OG_HEIGHT, {
    fit: 'cover',
    position: 'center',
  });

  let output;
  if (ext === '.png') {
    output = await pipeline
      .png({ compressionLevel: 9, palette: true, quality: 90, effort: 10 })
      .toBuffer();
  } else if (ext === '.jpg' || ext === '.jpeg') {
    output = await pipeline
      .jpeg({ quality: 85, mozjpeg: true, progressive: true })
      .toBuffer();
  } else {
    return { skipped: true };
  }

  const after = output.length;
  const savedPct = ((1 - after / before) * 100).toFixed(0);

  if (!dryRun) {
    await writeFile(filePath, output);
  }

  return { before, after, savedPct };
}

async function main() {
  try {
    await stat(dir);
  } catch {
    console.error(`directory not found: ${dir}`);
    process.exit(1);
  }

  const entries = await readdir(dir);
  const images = entries.filter((f) => /\.(png|jpe?g)$/i.test(f));

  if (images.length === 0) {
    console.log(`no PNG/JPG in ${dir}`);
    return;
  }

  console.log(`og-squish — ${dir}`);
  console.log(`target: ${OG_WIDTH}x${OG_HEIGHT}, <${TARGET_KB} KB${dryRun ? ' (dry run)' : ''}`);
  console.log('');

  let totalBefore = 0;
  let totalAfter = 0;

  for (const name of images) {
    const result = await optimizeOne(join(dir, name));
    if (result.skipped) continue;

    const flag = result.after > TARGET_KB * 1024 ? ' [over target]' : '';
    console.log(
      `  ${name.padEnd(24)} ${fmtKB(result.before).padStart(8)} -> ${fmtKB(result.after).padStart(8)}  (-${result.savedPct}%)${flag}`,
    );
    totalBefore += result.before;
    totalAfter += result.after;
  }

  console.log('');
  console.log(
    `total: ${fmtKB(totalBefore)} -> ${fmtKB(totalAfter)} (-${((1 - totalAfter / totalBefore) * 100).toFixed(0)}%)`,
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
