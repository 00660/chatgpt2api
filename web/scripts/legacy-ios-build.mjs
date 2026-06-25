import { readdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { transform } from "esbuild";

const chunksDir = join(process.cwd(), "out", "_next", "static", "chunks");
const legacyTarget = ["ios11"];
const globalThisShim = '(function(){if(typeof globalThis==="undefined"){this.globalThis=this;}}).call(typeof self!=="undefined"?self:typeof window!=="undefined"?window:this);';

async function listJavaScriptFiles(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...await listJavaScriptFiles(path));
      continue;
    }
    if (entry.isFile() && entry.name.endsWith(".js")) {
      files.push(path);
    }
  }
  return files;
}

const files = await listJavaScriptFiles(chunksDir);
for (const file of files) {
  const source = await readFile(file, "utf8");
  const result = await transform(source, {
    loader: "js",
    target: legacyTarget,
    minify: true,
    charset: "utf8",
    legalComments: "none",
  });
  await writeFile(file, `${globalThisShim}${result.code}`, "utf8");
}

console.log(`legacy-ios-build: transformed ${files.length} chunks for ${legacyTarget.join(", ")}`);
