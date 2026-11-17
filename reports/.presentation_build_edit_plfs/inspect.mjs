import { FileBlob, PresentationFile } from '@oai/artifact-tool';
const path = 'C:/Users/monis/OneDrive/Desktop/Employment_Outcome_Pathway_Grouping_After_Skilling/submission/PLFS_2023-24_Cross_Sectional_Study_final_submission_v2.pptx';
const p = await PresentationFile.importPptx(await FileBlob.load(path));
const r = await p.inspect({kind:'slide,textbox,shape,table,chart', maxChars:50000});
console.log(r.ndjson);
