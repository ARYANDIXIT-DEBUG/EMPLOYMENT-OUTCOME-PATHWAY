import { FileBlob, PresentationFile } from '@oai/artifact-tool';
const p=await PresentationFile.importPptx(await FileBlob.load('C:/Users/monis/OneDrive/Desktop/Employment_Outcome_Pathway_Grouping_After_Skilling/submission/Turkey_ISKUR_CA_presentation_v2.pptx'));
const s=p.slides.items[0]; console.log('bg',s.background.fill); console.log('shapes',s.shapes.items.map(x=>({id:x.id,position:x.position,fill:x.fill,geometry:x.geometry,text:String(x.text??'')})));
