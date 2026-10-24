#!/usr/bin/env node
// categorize-files.js <packed-file> <output-dir>
// Reads Repomix XML (the only input since P0-01 removed the Gitingest fallback), routes each file to 1+ layer
// slices, writes layer-<name>.xml + manifest.json to output-dir.
// Stdout: JSON summary { total_files, layers: { [name]: count } }

const fs   = require('fs');
const path = require('path');

const LAYER_PATTERNS = {
  runtime: [
    /^package\.json$/,
    /\.(toml|mod)$/,
    /Dockerfile/,
    /docker-compose/,
    /^\.nvmrc$/,
    /^\.python-version$/,
    /^requirements\.txt$/,
    /^Gemfile$/,
  ],
  framework: [
    /^(src|app|pages|routes|components)\//,
    /^server\./,
    /vite\.config/,
    /next\.config/,
    /webpack\.config/,
    /nuxt\.config/,
    /svelte\.config/,
  ],
  database: [
    /\/(db|migrations?|models?|repositories?|repository)\//,
    /\/schema\.(ts|js|sql|prisma)$/,
    /drizzle\.config/,
    /^prisma\//,
    /^alembic\//,
    /knexfile/,
  ],
  testing: [
    /\.(test|spec)\.(js|ts|jsx|tsx|py|rb|go|rs)$/,
    /\/(tests?|e2e|__tests__|cypress|spec)\//,
    /^(jest|vitest|pytest|rspec)\.config/,
    /playwright\.config/,
    /^conftest\.py$/,
  ],
  cicd: [
    /^\.github\//,
    /^\.circleci\//,
    /^\.gitlab-ci/,
    /^Makefile$/,
    /\/(deploy|deployment)\//,
    /^(fly|railway|render)\.toml$/,
    /^vercel\.json$/,
    /^netlify\.toml$/,
    /^\.travis\.yml$/,
  ],
  auth: [
    /\/(auth|authentication|authorization|middleware|guards?|policies?|permissions?)\//,
    /^\.env\.example$/,
    /^\.env\.sample$/,
    /^\.env\.template$/,
  ],
  ai_llm: [
    /\/(prompts?|agents?|evals?|llm|ai|embeddings?|chains?|tools?|memory|retrievers?)\//,
    /langchain/i,
    /openai/i,
    /anthropic/i,
    /\/(assistants?|bots?)\//,
  ],
  claude_code: [
    /^CLAUDE\.md$/,
    /^\.claude\//,
    /^skills\//,
    /^evals\/project-context\.json$/,
    /^\.mcp\.json$/,
  ],
};

const LAYER_NAMES = Object.keys(LAYER_PATTERNS);

function matchLayers(filePath) {
  return LAYER_NAMES.filter(layer =>
    LAYER_PATTERNS[layer].some(pattern => pattern.test(filePath))
  );
}

// Repomix XML only: any other input yields no blocks, and run() stops with an error.
function extractFileBlocks(content) {
  const blocks = [];
  const regex = /<file\s+path="([^"]+)"[^>]*>([\s\S]*?)<\/file>/g;
  let m;
  while ((m = regex.exec(content)) !== null) {
    blocks.push({ path: m[1], rawBlock: m[0] });
  }
  return blocks;
}

function run(packedPath, outputDir) {
  let content;
  try {
    content = fs.readFileSync(packedPath, 'utf8');
  } catch (e) {
    throw new Error(`Error reading ${packedPath}: ${e.message}`);
  }

  const fileBlocks = extractFileBlocks(content);
  if (fileBlocks.length === 0) {
    throw new Error('No file blocks found. Check Repomix output format.');
  }

  const layerBlocks = {};
  const manifest    = { total_files: fileBlocks.length, layers: {} };
  LAYER_NAMES.forEach(layer => {
    layerBlocks[layer] = [];
    manifest.layers[layer] = { file_count: 0, files: [] };
  });

  for (const { path: filePath, rawBlock } of fileBlocks) {
    for (const layer of matchLayers(filePath)) {
      layerBlocks[layer].push(rawBlock);
      manifest.layers[layer].file_count++;
      manifest.layers[layer].files.push(filePath);
    }
  }

  fs.mkdirSync(outputDir, { recursive: true });
  for (const layer of LAYER_NAMES) {
    const sliceContent = `<?xml version="1.0" encoding="UTF-8"?>\n<layer name="${layer}">\n${layerBlocks[layer].join('\n')}\n</layer>`;
    fs.writeFileSync(path.join(outputDir, `layer-${layer}.xml`), sliceContent);
  }
  fs.writeFileSync(path.join(outputDir, 'manifest.json'), JSON.stringify(manifest, null, 2));

  return {
    total_files: fileBlocks.length,
    layers: Object.fromEntries(LAYER_NAMES.map(l => [l, manifest.layers[l].file_count]))
  };
}

// CLI entry point
if (require.main === module) {
  const [,, packedPath, outputDir] = process.argv;
  if (!packedPath || !outputDir) {
    console.error('Usage: categorize-files.js <packed-file> <output-dir>');
    process.exit(1);
  }
  try {
    const result = run(packedPath, outputDir);
    console.log(JSON.stringify(result));
  } catch (e) {
    console.error(e.message);
    process.exit(1);
  }
}

module.exports = { matchLayers, extractFileBlocks, run };
