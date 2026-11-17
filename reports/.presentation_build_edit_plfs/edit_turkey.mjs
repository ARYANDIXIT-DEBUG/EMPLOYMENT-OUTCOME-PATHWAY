import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { FileBlob, PresentationFile } from '@oai/artifact-tool';
const workspaceDir='C:/Users/monis/OneDrive/Desktop/Employment_Outcome_Pathway_Grouping_After_Skilling';
const sourcePath=path.join(workspaceDir,'submission/Turkey_ISKUR_CA_presentation_v2.pptx');
const finalPath=path.join(workspaceDir,'submission/Turkey_ISKUR_CA_presentation_v3.pptx');
const buildDir=path.join(workspaceDir,'reports/.presentation_build_edit_plfs');
const skillDir='C:/Users/monis/.codex/plugins/cache/openai-primary-runtime/presentations/26.1105.12137/skills/presentations';
const presentation=await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const inspected=await presentation.inspect({kind:'slide,textbox,shape',maxChars:50000});
const recs=inspected.ndjson.split('\n').filter(Boolean).map(x=>JSON.parse(x));
const title=recs.find(x=>x.kind==='textbox' && x.text==='A longitudinal outcome analysis of the Turkey ISKUR evaluation');
const tealPanel=recs.find(x=>x.kind==='shape' && x.position?.left===900 && x.position?.top===0);
const emptyCard=recs.find(x=>x.kind==='shape' && x.position?.left===952 && x.position?.top===120);
if(!title || !tealPanel || !emptyCard) throw new Error('Cover objects did not match the reviewed layout.');
const fonts=[...new Set(recs.map(x=>x.style?.typeface).filter(Boolean))];
console.log('source fonts',fonts);
const slide=presentation.slides.items[0];
async function saveBlob(p,b){await fs.writeFile(p,new Uint8Array(await b.arrayBuffer()));}
await saveBlob(path.join(buildDir,'turkey-cover-before-edit.png'),await presentation.export({slide,format:'png',scale:1}));
presentation.delete([tealPanel.id,emptyCard.id]);
presentation.resolve(title.id).text.replace('A longitudinal outcome analysis of the Turkey ISKUR evaluation','A descriptive sequence analysis of the Turkey ISKUR evaluation');
const after=await presentation.inspect({kind:'slide,textbox,shape',maxChars:50000});
const afterRecords=after.ndjson.split('\n').filter(Boolean).map(x=>JSON.parse(x));
if(afterRecords.some(x=>x.text==='A longitudinal outcome analysis of the Turkey ISKUR evaluation')) throw new Error('Old cover wording remains.');
if(!afterRecords.some(x=>x.text==='A descriptive sequence analysis of the Turkey ISKUR evaluation')) throw new Error('New cover wording missing.');
await saveBlob(path.join(buildDir,'turkey-cover-after-edit.png'),await presentation.export({slide,format:'png',scale:1}));
const draftPath=path.join(buildDir,'turkey-cover-candidate.pptx');
await (await PresentationFile.exportPptx(presentation)).save(draftPath);
const {finalizePresentation}=await import(pathToFileURL(path.join(skillDir,'container_tools/artifact_tool_utils.mjs')).href);
const result=await finalizePresentation({
 explicitTotalSlideCount:8,
 requiredNativeTableOwnerSlides:[],requiredNativeChartOwnerSlides:[],
 workspaceDir,candidatePath:draftPath,finalPath,
 pythonExecutable:'C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1105-1297-0_26.1105.1297.0_x64__3k8sg7r9htsxt/dependencies/python/python.exe',
 integrityValidatorPath:path.join(skillDir,'container_tools/inspect_presentation_package_integrity.py'),
 layoutValidatorPath:path.join(skillDir,'container_tools/inspect_presentation_layout_geometry.py'),
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit'],
 fontPolicy:{basis:'reference',families:fonts,referencePath:sourcePath,referenceSha256:'ac99a19d416f6ccb244cd78e657f0acdc58364453febdf3aa1e768812de03519'},
 verifyArtifactToolImport:true,
 receiptPath:path.join(buildDir,'turkey-cover-validation.json'),
});
console.log(JSON.stringify(result));
