import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { FileBlob, PresentationFile } from '@oai/artifact-tool';

const workspaceDir = 'C:/Users/monis/OneDrive/Desktop/Employment_Outcome_Pathway_Grouping_After_Skilling';
const sourcePath = path.join(workspaceDir, 'submission/PLFS_2023-24_Cross_Sectional_Study_final_submission_v2.pptx');
const finalPath = path.join(workspaceDir, 'submission/PLFS_2023-24_Cross_Sectional_Study_final_submission_v3.pptx');
const buildDir = path.join(workspaceDir, 'reports/.presentation_build_edit_plfs');
const skillDir = 'C:/Users/monis/.codex/plugins/cache/openai-primary-runtime/presentations/26.1105.12137/skills/presentations';
const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const inspected = await presentation.inspect({kind:'slide,textbox,shape,table,chart', maxChars:50000});
const records = inspected.ndjson.split('\n').filter(Boolean).map(x=>JSON.parse(x));
const oldText = 'Full suite: 183 passed, 3 existing warnings.';
const target = records.find(x=>x.kind==='textbox' && x.text===oldText);
if (!target) throw new Error('Could not find the stale test status text.');
const slide = presentation.slides.items[target.slideIndex];
async function saveBlob(p, blob) { await fs.writeFile(p, new Uint8Array(await blob.arrayBuffer())); }
await saveBlob(path.join(buildDir,'slide-08-before.png'), await presentation.export({slide,format:'png',scale:1}));
presentation.resolve(target.id).text.replace(oldText, 'Full suite: 188 passed, 1 failed, 3 warnings (PLFS source file missing).');
const after = await presentation.inspect({target:{id:target.id,beforeLines:1,afterLines:1},kind:'textbox',maxChars:1000});
console.log(after.ndjson);
await saveBlob(path.join(buildDir,'slide-08-after.png'), await presentation.export({slide,format:'png',scale:1}));
const draftPath = path.join(buildDir,'candidate.pptx');
await (await PresentationFile.exportPptx(presentation)).save(draftPath);
const { finalizePresentation } = await import(pathToFileURL(path.join(skillDir,'container_tools/artifact_tool_utils.mjs')).href);
const result = await finalizePresentation({
  explicitTotalSlideCount: 8,
  requiredNativeTableOwnerSlides: [],
  requiredNativeChartOwnerSlides: [],
  workspaceDir,
  candidatePath: draftPath,
  finalPath,
  pythonExecutable: 'C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1105-1297-0_26.1105.1297.0_x64__3k8sg7r9htsxt/dependencies/python/python.exe',
  integrityValidatorPath: path.join(skillDir,'container_tools/inspect_presentation_package_integrity.py'),
  layoutValidatorPath: path.join(skillDir,'container_tools/inspect_presentation_layout_geometry.py'),
  layoutArgs: ['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit'],
  fontPolicy: {basis:'reference',families:['Arial'],referencePath:sourcePath,referenceSha256:'3353429b3169b21d20452cc931954da6aaf1696fff62def8f7b95de880be855f'},
  verifyArtifactToolImport: true,
  receiptPath: path.join(buildDir,'validation.json'),
});
console.log(JSON.stringify(result));

