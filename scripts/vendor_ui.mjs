import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dest = path.join(project, 'static', 'assets');
fs.mkdirSync(path.join(dest, 'fonts'), { recursive: true });

for (const [source, target] of [
  ['marked/lib/marked.umd.js', 'marked.umd.js'],
  ['dompurify/dist/purify.min.js', 'purify.min.js'],
  ['katex/dist/katex.min.js', 'katex.min.js'],
  ['katex/dist/katex.min.css', 'katex.min.css'],
]) {
  const file = path.join(project, 'node_modules', source);
  if (!fs.existsSync(file)) throw new Error(`Missing dependency file: ${file}`);
  fs.copyFileSync(file, path.join(dest, target));
  console.log(`Vendored ${target}`);
}
const sourceFonts = path.join(project, 'node_modules', 'katex', 'dist', 'fonts');
for (const name of fs.readdirSync(sourceFonts)) {
  if (name.endsWith('.woff2') || name.endsWith('.woff') || name.endsWith('.ttf')) {
    fs.copyFileSync(path.join(sourceFonts, name), path.join(dest, 'fonts', name));
  }
}
console.log('LocalMind offline Markdown/LaTeX resources copied into static/assets.');
