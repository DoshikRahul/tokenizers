ACI-Benchmark Data
---------------------

This data contains 207 full-encounter dialogue-note pairs for note generation from doctor-patient conversations.

To replicate experiments from the paper please follow directions from the repo:
https://github.com/wyim/aci-bench

Train/validation/test data from the two challenges below, can be found in the challenge_data folder:
https://github.com/abachaa/MEDIQA-Chat-2023
https://www.imageclef.org/2023/medical/mediqa

Data for experimenting with ASR instead of human transcriptons or ASR-corrected data instead of ASR transcripts may be found in the src_experiment_data folder.

Each data split will have the src-target file (with an ID, dialogue, note column) denoted by a *.csv file, as well as a metadata file (with additional metadata such as patient name and chief complaints) denoted by a *_metadata.csv file.

To join dataframes, please use the id or encounter_id columns.

Simple folder guide
-------------------

1. challenge_data/ - The main 207 encounters:
   - train.csv: 67 encounters
   - valid.csv: 20 encounters
   - clinicalnlp_taskB_test1.csv: 40 encounters
   - clinicalnlp_taskC_test2.csv: 40 encounters
   - clef_taskC_test3.csv: 40 encounters

   Each row contains a source label, encounter ID, doctor-patient conversation
   (dialogue), and an existing reference clinical note (note).

   Each CSV has a matching *_metadata.csv with patient details and complaints.
   These describe the same encounters, not additional patients. Some details
   are missing. Join the main CSV and its metadata using encounter_id.

2. src_experiment_data/ - Alternative transcripts of selected main encounters.
   - asr: automatic speech-recognition transcript
   - asrcorr: corrected speech-recognition transcript
   - humantrans: human transcript

   Example: test1_aci_asrcorr.csv means test1 split, aci source group,
   corrected transcript. It also has a matching metadata file; join using id.
   Not every source and split has every transcript version.

The many files come from splits, metadata, and transcript versions. Do not
combine all files as separate patients. Main transcripts use mixed transcript
types; corrected alternatives can change clinical details.

This folder contains text data, not audio, images, or separate lab tables.

For our Phase 1 project, give each conversation from challenge_data/ to a
patient agent. It answers follow-up questions using only that conversation;
doctor agents use this simulated consultation to generate SOAP notes. Missing
details stay unknown. Keep the existing reference notes out of all agent
inputs; they can be used for comparison later.


Complete encounter example: D2N001
---------------------------------

Conversation and reference note source:
/home/surya/Desktop/tokenizers/aci-bench-corpus/challenge_data/train.csv

Metadata source:
/home/surya/Desktop/tokenizers/aci-bench-corpus/challenge_data/train_metadata.csv

Mapping: match encounter_id = "D2N001" in both files.
The matching metadata gives the original source id = "VA049".
The conversation, reference note, and metadata below are copied in full
from these CSV records; they are not generated output.

1. Record identifiers (from train.csv)
-------------------------------------
{
  "dataset": "virtassist",
  "encounter_id": "D2N001"
}

2. Complete conversation (dialogue column in train.csv)
------------------------------------------------------
[doctor] hi , martha . how are you ?
[patient] i'm doing okay . how are you ?
[doctor] i'm doing okay . so , i know the nurse told you about dax . i'd like to tell dax a little bit about you , okay ?
[patient] okay .
[doctor] martha is a 50-year-old female with a past medical history significant for congestive heart failure , depression and hypertension who presents for her annual exam . so , martha , it's been a year since i've seen you . how are you doing ?
[patient] i'm doing well . i've been traveling a lot recently since things have , have gotten a bit lighter . and i got my , my vaccine , so i feel safer about traveling . i've been doing a lot of hiking . uh , went to washington last weekend to hike in northern cascades, like around the mount baker area .
[doctor] nice . that's great . i'm glad to hear that you're staying active , you know . i , i just love this weather . i'm so happy the summer is over . i'm definitely more of a fall person .
[patient] yes , fall foliage is the best .
[doctor] yeah . um , so tell me , how are you doing with the congestive heart failure ? how are you doing watching your diet ? i know we've talked about watching a low sodium diet . are you doing okay with that ?
[patient] i've been doing well with that . i resisted , as much , as i could , from the tater tots , you know , the soft pretzels , the salty foods that i , i love to eat . and i've been doing a really good job .
[doctor] okay , all right . well , i'm glad to hear that . and you're taking your medication ?
[patient] yes .
[doctor] okay , good . and any symptoms like chest pains , shortness of breath , any swelling in your legs ?
[patient] no , not that i've noticed .
[doctor] okay , all right . and then in terms of your depression , i know that we tried to stay off of medication in the past because you're on medications for your other problems . how are you doing ? and i know that you enrolled into therapy . is that helping ? or-
[patient] yeah , it's been helping a lot . i've been going every week , um , for the past year since my last annual exam . and that's been really helpful for me .
[doctor] okay . so , no , no issues , no feelings of wanting to harm yourself or hurt others ?
[patient] no , nothing like that .
[doctor] okay , all right . and then in terms of your high blood pressure , i know that you and i have kind of battled in the past with you remembering to take some of your blood pressure medications . how are you doing with that ?
[patient] i'm still forgetting to take my blood pressure medication . and i've noticed when work gets more stressful , my blood pressure goes up .
[doctor] okay . and , and so how has work going for you ?
[patient] it's been okay . it's been a lot of long hours , late nights . a lot of , um , you know , fiscal year end data that i've been having to pull . so , a lot of responsibility , which is good . but with the responsibility comes the stress .
[doctor] yeah , okay , all right . i understand . um , all right . well , i know that you did a review of system sheet when you checked in with the nurse . i know that you were endorsing some nasal congestion from some of the fall pollen and allergies . any other symptoms , nausea or vomiting , abdominal pain , anything like that ?
[patient] no , nothing like that .
[doctor] no , okay , all right . well , i'm gon na go ahead and do a quick physical exam , okay ?
[patient] okay .
[doctor] hey , dragon , show me the blood pressure . so , yeah , looking at your blood pressure today here in the office , it is a little elevated . you know , it could just , you could just be nervous . uh , let's look at some of the past readings . hey , dragon , show me the blood pressure readings . hey , dragon , show me the blood pressure readings . here we go . uh , so they are running on the higher side . um , y- you know , i , i do think that , you know , i'd like to see you take your medication a little bit more , so that we can get that under control a little bit better , okay ?
[patient] okay .
[doctor] so , i'm just gon na check out your heart and your lungs . and you know , let you know what i find , okay ?
[patient] okay .
[doctor] okay . so , on your physical examination , you know , everything looks good . on your heart exam , i do appreciate a three out of six systolic ejection murmur , which i've heard in the past , okay ? and on your lower extremities , i do appreciate one plus pitting edema , so you do have a little bit of fluid in your legs , okay ?
[patient] okay .
[doctor] let's go ahead , i wan na look at some of your results , okay ? hey , dragon , show me the echocardiogram . so , this is the result of the echocardiogram that we did last year . it showed that you have that low-ish pumping function of your heart at about 45 % . and it also sh- shows some mitral regurgitation , that's that heart murmur that i heard , okay ?
[doctor] um , hey , dragon , show me the lipid panel . so , looking at your lipid panel from last year , you know , everything , your cholesterol was like , a tiny bit high . but it was n't too , too bad , so i know you're trying to watch your diet . so , we'll repeat another one this year , okay ?
[patient] okay .
[doctor] um , so i wan na just go over a little bit about my assessment and my plan for you , okay ? so , for your first problem your congestive heart failure , um , i wan na continue you on your current medications . but i do wan na increase your lisinopril to 40 milligrams a day , just because your blood pressure's high . and you know , you are retaining a little bit of fluid . i also wan na start you on some lasix , you know , 20 milligrams a day . and have you continue to watch your , your diet , okay ?
[patient] okay .
[doctor] i also wan na repeat another echocardiogram , okay ?
[patient] all right .
[doctor] hey , dragon , order an echocardiogram . from a depression standpoint , it sounds like you're doing really well with that . so , i'm , i'm really happy for you . i'm , i'm glad to see that you're in therapy and you're doing really well . i do n't feel the need to start you on any medications this year , unless you feel differently .
[patient] no , i feel the same way .
[doctor] okay , all right . and then for your last problem your hypertension , you know , again i , i , i think it's out of control . but we'll see , i think , you know , i'd like to see you take the lisinopril as directed , okay ? uh , i want you to record your blood pressures within the patient , you know , take your blood pressure every day . record them to me for like , about a week , so i have to see if we have to add another agent , okay ? 'cause we need to get that under better control for your heart failure to be more successful , okay ?
[patient] okay .
[doctor] do you have any questions ? , and i forgot . for your annual exam , you're due for a mammogram , so we have to schedule for that , as well , okay ?
[patient] okay .
[doctor] okay . do you have any questions ?
[patient] can i take all my pills at the same time ?
[doctor] yeah .
[patient] 'cause i've been trying to take them at different times of the day , 'cause i did n't know if it was bad to take them all at once or i should separate them . i do n't know .
[doctor] yeah . you can certainly take them , you know , all at the same time , as long , as yeah , they're all one scale . you can take them all at the same time . just set an alarm-
[patient] okay .
[doctor] . some time during the day to take them , okay ?
[patient] that might help me remember better .
[doctor] all right . that sounds good . all right , well , it's good to see you .
[patient] good seeing you too .
[doctor] hey , dragon , finalize the note .

3. Complete reference clinical note (note column in train.csv)
-------------------------------------------------------------
CHIEF COMPLAINT

Annual exam.

HISTORY OF PRESENT ILLNESS

Martha Collins is a 50-year-old female with a past medical history significant for congestive heart failure, depression, and hypertension who presents for her annual exam. It has been a year since I last saw the patient.

The patient has been traveling a lot recently since things have gotten a bit better. She reports that she got her COVID-19 vaccine so she feels safer about traveling. She has been doing a lot of hiking.

She reports that she is staying active. She has continued watching her diet and she is doing well with that. The patient states that she is avoiding salty foods that she likes to eat. She has continued utilizing her medications. The patient denies any chest pain, shortness of breath, or swelling in her legs.

Regarding her depression, she reports that she has been going to therapy every week for the past year. This has been really helpful for her. She denies suicidal or homicidal ideation.

The patient reports that she is still forgetting to take her blood pressure medication. She has noticed that when work gets more stressful, her blood pressure goes up. She reports that work has been going okay, but it has been a lot of long hours lately.

She endorses some nasal congestion from some of the fall allergies. She denies any other symptoms of nausea, vomiting, abdominal pain.

REVIEW OF SYSTEMS

• Ears, Nose, Mouth and Throat: Endorses nasal congestion from allergies.
• Cardiovascular: Denies chest pain or dyspnea on exertion.
• Respiratory: Denies shortness of breath.
• Gastrointestinal: Denies abdominal pain, nausea, or vomiting.
• Psychiatric: Endorses depression. Denies suicidal or homicidal ideations.

PHYSICAL EXAMINATION

• Cardiovascular: Grade 3/6 systolic ejection murmur.
1+ pitting edema of the bilateral lower extremities.

VITALS REVIEWED

• Blood Pressure: Elevated.

RESULTS

Echocardiogram demonstrates decreased ejection fraction of 45%. Mitral regurgitation is present.

Lipid panel: Elevated cholesterol.

ASSESSMENT AND PLAN

Martha Collins is a 50-year-old female with a past medical history significant for congestive heart failure, depression, and hypertension who presents for her annual exam.

Congestive heart failure.
• Medical Reasoning: She has been compliant with her medication and dietary modifications. Her previous year's echocardiogram demonstrated a reduced ejection fraction of 45%, as well as some mitral regurgitation. Her cholesterol levels were slightly elevated on her lipid panel from last year.
• Additional Testing: We will order a repeat echocardiogram. We will also repeat a lipid panel this year.
• Medical Treatment: She will continue with her current medications. We will increase her lisinopril to 40 mg daily and initiate Lasix 20 mg daily.
• Patient Education and Counseling: I encouraged her to continue with dietary modifications.

Depression.
• Medical Reasoning: She is doing well with weekly therapy.

Hypertension.
• Medical Reasoning: She has been compliant with dietary modifications but has been inconsistent with the use of her medication. She attributes elevations in her blood pressure to increased stress.
• Medical Treatment: We will increase her lisinopril to 40 mg daily as noted above.
• Patient Education and Counseling: I encouraged the patient to take her lisinopril as directed. I advised her to monitor her blood pressures at home for the next week and report them to me.

Healthcare maintenance.
• Medical Reasoning: The patient is due for her routine mammogram.
• Additional Testing: We will order a mammogram and have this scheduled for her.

Patient Agreements: The patient understands and agrees with the recommended medical treatment plan.


4. Complete metadata (matching row in train_metadata.csv)
--------------------------------------------------------
Empty strings ("") mean the dataset did not supply that value.
{
  "dataset": "virtassist",
  "encounter_id": "D2N001",
  "id": "VA049",
  "doctor_name": "",
  "patient_gender": "female",
  "patient_age": "50",
  "patient_firstname": "Martha",
  "patient_familyname": "Collins",
  "cc": "annual exam",
  "2nd_complaints": "congestive heart failure;depression;hypertension"
}
