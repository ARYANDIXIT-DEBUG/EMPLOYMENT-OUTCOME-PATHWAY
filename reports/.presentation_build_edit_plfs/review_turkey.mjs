import fs from 'node:fs/promises';
import path from 'node:path';
import { FileBlob, PresentationFile } from '@oai/artifact-tool';
const p=await PresentationFile.importPptx(await FileBlob.load('C:/Users/monis/OneDrive/Desktop/Employment_Outcome_Pathway_Grouping_After_Skilling/submission/Turkey_ISKUR_CA_presentation_v2.pptx'));
const dir='C:/Users/monis/OneDrive/Desktop/Employment_Outcome_Pathway_Grouping_After_Skilling/reports/.presentation_build_edit_plfs';
async function save(n,b){await fs.writeFile(path.join(dir,n),new Uint8Array(await b.arrayBuffer()));}
for (let i=0;i<p.slides.items.length;i++) await save(`turkey-slide-${String(i+1).padStart(2,'0')}.png`,await p.export({slide:p.slides.items[i],format:'png',scale:1}));
await save('turkey-montage.webp',await p.export({format:'webp',montage:true}));
console.log('rendered',p.slides.items.length,'Turkey slides');
