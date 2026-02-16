/**
 * Renames .js → .cjs and .d.ts → .d.cts in dist/cjs so Node resolves
 * them correctly when the package.json has "type": "module".
 */
import { readdirSync, renameSync, readFileSync, writeFileSync } from 'fs';
import { join, extname } from 'path';

const dir = new URL('../dist/cjs', import.meta.url).pathname;

function walk(d) {
  for (const entry of readdirSync(d, { withFileTypes: true })) {
    const full = join(d, entry.name);
    if (entry.isDirectory()) {
      walk(full);
      continue;
    }
    if (entry.name.endsWith('.js')) {
      // Fix require paths inside the file
      let content = readFileSync(full, 'utf8');
      content = content.replace(/require\("\.(.+?)\.js"\)/g, 'require(".$1.cjs")');
      writeFileSync(full, content);
      renameSync(full, full.replace(/\.js$/, '.cjs'));
    } else if (entry.name.endsWith('.d.ts')) {
      renameSync(full, full.replace(/\.d\.ts$/, '.d.cts'));
    } else if (entry.name.endsWith('.js.map')) {
      renameSync(full, full.replace(/\.js\.map$/, '.cjs.map'));
    }
  }
}

walk(dir);
console.log('CJS fixup complete.');
