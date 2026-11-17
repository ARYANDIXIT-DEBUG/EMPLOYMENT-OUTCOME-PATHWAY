import { FileBlob, PresentationFile } from '@oai/artifact-tool';
const p=await PresentationFile.importPptx(await FileBlob.load('C:/Users/monis/OneDrive/Desktop/Employment_Outcome_Pathway_Grouping_After_Skilling/submission/Turkey_ISKUR_CA_presentation_v3.pptx'));
const r=await p.inspect({kind:'slide,textbox,shape',maxChars:12000}); console.log(r.ndjson);
