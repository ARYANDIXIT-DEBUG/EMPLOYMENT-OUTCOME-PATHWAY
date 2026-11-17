import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { Presentation, PresentationFile } from '@oai/artifact-tool';

const workspaceDir = 'C:/Users/monis/OneDrive/Documents/Employment_Outcome_Pathway_Grouping_After_Skilling_FINAL';
const buildDir = path.join(workspaceDir, 'reports/.presentation_build');
const finalPath = path.join(workspaceDir, 'submission/PLFS_2023-24_Cross_Sectional_Study_final_submission_v2.pptx');
const skillDir = 'C:/Users/monis/.codex/plugins/cache/openai-primary-runtime/presentations/26.1105.12137/skills/presentations';
const BLUE = '#123B56', TEAL = '#176B5B', ORANGE = '#C87E18', GREY = '#52606D', LIGHT = '#EAF0F3', WHITE = '#FFFFFF', DARK = '#172B3A';
const p = Presentation.create({ slideSize: { width: 1280, height: 720 } });
const font = 'Arial';
function textbox(slide, text, x, y, w, h, size=26, color=DARK, bold=false) {
  const sh = slide.shapes.add({ geometry:'textbox', position:{left:x,top:y,width:w,height:h}, fill:'none', line:{style:'solid',fill:'none',width:0} });
  sh.text = text;
  sh.text.style = { fontFamily:font, fontSize:size, color, bold, wrap:true, verticalAlignment:'middle' };
  return sh;
}
function base(title, kicker='') {
  const s=p.slides.add(); s.background.fill=WHITE;
  if (kicker) textbox(s,kicker.toUpperCase(),72,40,1120,24,16,TEAL,true);
  textbox(s,title,72,kicker?74:54,1136,70,46,BLUE,true);
  const line=s.shapes.add({geometry:'rect',position:{left:72,top:145,width:72,height:5},fill:TEAL,line:{style:'solid',fill:TEAL,width:0}});
  return s;
}
function bullets(slide, items, x=88, y=180, width=1080, fontSize=27, gap=62) {
  items.forEach((item,i)=>{
    textbox(slide,'•',x,y+i*gap,30,42,fontSize,TEAL,true);
    textbox(slide,item,x+38,y+i*gap,width-38,50,fontSize,DARK,false);
  });
}
function note(slide, text) { slide.speakerNotes.text=text; }

// 1 — title
{
 const s=p.slides.add(); s.background.fill=WHITE;
 textbox(s,'Employment Outcome Pathway\nGrouping After Skilling',72,112,940,160,58,BLUE,true);
 textbox(s,'SIH26135  |  PLFS 2023–24, MoSPI Catalogue 213',76,302,1080,42,25,TEAL,true);
 textbox(s,'Revised real-data study: annual cross-sectional CWS indicators among respondents reporting formal vocational training',76,382,990,110,30,DARK,false);
 textbox(s,'Descriptive estimates • First visit • Rural and urban',76,552,900,38,22,GREY,false);
 note(s,'The official project identity is retained. The real-data question is narrowed because the available documentation does not establish persistent person linkage or training-before-observation timing. Sources: reports/14_final_design_and_results.md; MoSPI PLFS 2023–24 Catalogue 213 documents in docs/mospi/.');
}
// 2 — question and cohort
{
 const s=base('Question and cohort','Research design');
 textbox(s,'Research question',82,185,300,40,25,TEAL,true);
 textbox(s,'Among PLFS respondents aged 15–59 reporting formal vocational/technical training, what is the annual weighted distribution of CWS at first visit?',82,228,1060,110,31,DARK,true);
 bullets(s,[
   'Source: perv1 first-visit records, Q1–Q4',
   'Cohort: age 15–59 and b4q12 = 1',
   'Population coverage: rural and urban, estimated separately and combined',
   'No person linking; no transition or causal claim'
 ],82,378,1090,25,58);
 note(s,'Instruction Manual Vol. II, Schedule 10.4, pp. 5–6: formal vocational/technical training particulars are collected for ages 12–59 and those with code 1 in Block 4 column 12. The study uses ages 15–59 for CWS indicators. Catalogue 213 DDI describes annual CWS estimates for rural and urban areas.');
}
// 3 — definitions and weights
{
 const s=base('Documented fields and annual weight','Definitions');
 bullets(s,[
   'b4q12 = 1: formal vocational/technical training detail group',
   'CWS 11–72 employed; 81/82 unemployed; 91–98 out of labour force',
   'Annual weight = MULT / (100 if NSS = NSC else 200) / NO_QTR',
   'Blank CWS stays missing; 99 and individual 91–98 labels remain unresolved'
 ],82,184,1100,25,67);
 textbox(s,'Sources: PLFS 2023–24 user rider §B; Instruction Manual Vol. I §3.6.14; Vol. II Schedule 10.4.',82,510,1080,56,20,GREY,false);
 note(s,'The rider states combined subsample weights as MULT/100 when NSS=NSC and MULT/200 otherwise, and says annual MULT may be divided by NO_QTR. Instruction Manual Vol. I §3.6.14 documents broad CWS categories only. No specific label is assigned to codes 91–98; 99 remains unresolved.');
}
// 4 — validation
{
 const s=base('Real-data validation','Sample checks');
 textbox(s,'13,027',82,190,460,88,72,TEAL,true);
 textbox(s,'eligible first-visit respondents',82,270,460,42,25,DARK,false);
 textbox(s,'5,132 rural',82,380,450,50,34,BLUE,true);
 textbox(s,'7,895 urban',82,438,450,50,34,BLUE,true);
 textbox(s,'0',680,190,230,88,72,TEAL,true);
 textbox(s,'selected records with missing or unclassified CWS',680,270,470,66,25,DARK,false);
 textbox(s,'0',680,392,230,88,72,TEAL,true);
 textbox(s,'first-visit record-key collisions',680,474,470,50,25,DARK,false);
 textbox(s,'405,132 records were outside the age/training rule; no raw rows were deleted.',82,584,1080,44,22,GREY,false);
 note(s,'Reproduced from perv1.csv. Selected records by Q1/Q2/Q3/Q4: 3,452 / 3,214 / 3,173 / 3,188. Annual-weight inputs were present for all selected records; NO_QTR was 4 for 13,025 and 3 for 2.');
}
// 5 — CWS distribution figure
{
 const s=base('Annual CWS distribution','Weighted results');
 s.images.add({blob:new Uint8Array(await fs.readFile(path.join(workspaceDir,'outputs/cross_sectional/real/cws_weighted_shares.png'))),contentType:'image/png',alt:'Stacked bars showing weighted employed, unemployed, and out-of-labour-force CWS shares for combined, rural, and urban trained cohorts',fit:'contain',position:{left:115,top:165,width:1050,height:470}});
 textbox(s,'Combined cohort: employed 62.24%  |  unemployed 9.21%  |  out of labour force 28.55%',86,632,1110,42,22,DARK,true);
 note(s,'Figure is generated from outputs/cross_sectional/real/cws_estimates.csv. Combined/rural/urban weighted shares are based on the documented annual weights. No selected CWS outcomes were missing or unclassified.');
}
// 6 — indicators
{
 const s=base('Employment indicators','Weighted point estimates');
 const values=[
  ['Population','n','Weighted population','WPR','LFPR','UR'],
  ['Combined','13,027','31,213,646','62.24%','71.45%','12.90%'],
  ['Rural','5,132','15,713,816','61.17%','70.91%','13.73%'],
  ['Urban','7,895','15,499,830','63.32%','72.01%','12.06%'],
 ];
 const t=s.tables.add({rows:4,columns:6,left:72,top:190,width:1136,height:260,values});
 for(let r=0;r<4;r++) for(let c=0;c<6;c++) {
   const cell=t.getCell(r,c); cell.text.style={fontFamily:font,fontSize:r===0?18:21,color:r===0?WHITE:DARK,bold:r===0||c===0};
   cell.fill=r===0?BLUE:(r%2===0?LIGHT:WHITE);
 }
 textbox(s,'WPR = employed / population; LFPR = (employed + unemployed) / population; UR = unemployed / labour force.',82,500,1080,52,22,DARK,false);
 textbox(s,'Point estimates only; design-based standard errors and confidence intervals are not implemented.',82,574,1080,52,21,GREY,false);
 note(s,'Values are reproduced from outputs/cross_sectional/real/employment_indicators.csv. Weighted population totals use the annual multiplier procedure in the Catalogue 213 rider §B. Rates use the stated denominators.');
}
// 7 — why no clusters and no pathway claim
{
 const s=base('Why there are no real-data clusters','Limits');
 bullets(s,[
   'CWS is one categorical outcome; clustering it alone would reproduce its categories.',
   'Occupation and industry are recorded for people with work records, so including them changes the cohort.',
   'No profiling-variable whitelist is inferred from the permission confirmation.',
   'The 365-day completion flag gives no exact date before the CWS reference week.',
   'The person file has no nonresponse field; a separate response adjustment cannot be assessed.',
   'No post-training, employment-transition, pathway or causal claim is supported.'
 ],82,180,1110,24,75);
 note(s,'No PAM or hierarchical clustering was run. They remain in the project for future use only if a permitted and statistically defensible multivariate feature space is established. Instruction Manual Vol. II, Schedule 10.4, p. 6 documents the last-365-days completion flag, not a completion date.');
}
// 8 — reproducibility and next steps
{
 const s=base('Reproducibility and remaining work','Submission status');
 bullets(s,[
   'Run: python -B -m src.cross_sectional',
   'Saved tables, figures and provenance: outputs/cross_sectional/real/',
   'The dashboard reads saved, hash-checked results only.',
   'Full suite: 183 passed, 3 existing warnings.',
   'Instructor approval and required MoSPI permissions are user-confirmed.',
   'Design-based uncertainty is future work; do not claim statistical significance.'
 ],82,184,1100,24,68);
 textbox(s,'The original longitudinal gate remains closed: CHECKPOINT 1 unresolved; data.plan = UNSET.',82,568,1100,66,24,ORANGE,true);
 note(s,'The run records SHA-256 hashes for the input CSV, config.yaml, and analysis module. No random seed is used because the descriptive estimator is deterministic. The original trajectory pipeline, model-selection rules and synthetic test outputs were preserved. See reports/14_final_design_and_results.md.');
}

for (let i=0;i<p.slides.items.length;i++) {
 const blob=await p.export({slide:p.slides.items[i],format:'png',scale:1});
 await fs.writeFile(path.join(buildDir,`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await blob.arrayBuffer()));
}
const pptx=await PresentationFile.exportPptx(p);
const candidate=path.join(buildDir,'candidate.pptx');
await pptx.save(candidate);
const {finalizePresentation}=await import(pathToFileURL(path.join(skillDir,'container_tools/artifact_tool_utils.mjs')).href);
const receipt=path.join(buildDir,'validation-final-submission-v2.json');
const result=await finalizePresentation({
 workspaceDir,candidatePath:candidate,finalPath,
 pythonExecutable:'C:/Users/monis/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',
 integrityValidatorPath:path.join(skillDir,'container_tools/inspect_presentation_package_integrity.py'),
 layoutValidatorPath:path.join(skillDir,'container_tools/inspect_presentation_layout_geometry.py'),
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit','--require-native-table-slide','6'],
 requiredNativeTableOwnerSlides:[6],
 requirements:{explicitTotalSlideCount:8,requiredNativeTableOwnerSlides:[6],tableArithmeticContracts:[]},
 fontPolicy:{basis:'design',families:['Arial']},verifyArtifactToolImport:true,receiptPath:receipt,
});
console.log(JSON.stringify({finalPath,receipt,result},null,2));
