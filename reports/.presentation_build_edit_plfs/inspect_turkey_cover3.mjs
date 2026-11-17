import { FileBlob, PresentationFile } from '@oai/artifact-tool';
const p=await PresentationFile.importPptx(await FileBlob.load('C:/Users/monis/OneDrive/Desktop/Employment_Outcome_Pathway_Grouping_After_Skilling/submission/Turkey_ISKUR_CA_presentation_v2.pptx'));
const pr=p.toProto(); console.log(JSON.stringify(pr.slides[0],null,2).slice(0,5000));
