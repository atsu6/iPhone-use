import { build } from 'esbuild';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const uiRoot = new URL('./', import.meta.url);
const assetRoot = new URL('../assets/', import.meta.url);
const output = await build({
  entryPoints: [fileURLToPath(new URL('src/app.ts', uiRoot))],
  bundle: true,
  platform: 'browser',
  target: 'es2022',
  format: 'esm',
  minify: true,
  write: false,
  legalComments: 'inline',
});
const [html, css] = await Promise.all([
  readFile(new URL('index.html', uiRoot), 'utf8'),
  readFile(new URL('style.css', uiRoot), 'utf8'),
]);
// Callbacks preserve literal $` and $' sequences in the bundled SDK.
const widget = html
  .replace('/*__STYLE__*/', () => css)
  .replace('/*__SCRIPT__*/', () => output.outputFiles[0].text.replace(/<\/script/gi, '<\\/script'));
await mkdir(assetRoot, { recursive: true });
await writeFile(new URL('phone-screen.html', assetRoot), widget);
console.log('Built self-contained phone-screen.html.');
