# TRAIS LLM Testing Questions - Golden Patient 1

## Comprehensive Test Suite for Information Retrieval - Diabetes/Metabolic Syndrome Patient

---

## Category 1: Patient Identification & Demographics (10 questions)

### Quick Identity Verification

1. **What is this patient's name?**

   - Expected: Serafina151 Kellye282 Lesch175
   - Use case: Verify correct patient chart

2. **How old is this patient?**

   - Expected: 69 years old
   - Use case: Age-appropriate decision making

3. **When was the patient born?**

   - Expected: 1956
   - Use case: Verify demographics

4. **What is the patient's gender?**
   - Expected: Female
   - Use case: Gender-specific considerations

### Quick Clinical Overview

6. **What are this patient's active diagnoses?**

   - Expected: Type 2 diabetes, essential hypertension, hyperlipidemia, hypothyroidism, obesity
   - Use case: Quick problem list review before visit

7. **Give me a brief summary of this patient.**

   - Expected: 69F with Type 2 diabetes, HTN, hyperlipidemia, hypothyroidism, obesity diagnosed 2006, on 4 chronic meds
   - Use case: Quick refresh before entering exam room

8. **When were this patient's chronic conditions first diagnosed?**

   - Expected: August 2006
   - Use case: Understanding disease duration

9. **What category of patient is this?**

   - Expected: Diabetic/metabolic syndrome patient
   - Use case: Mental model for visit planning

10. **Is this a new patient or established?**
    - Expected: Established (visits since childhood)
    - Use case: Understanding patient relationship

---

## Category 2: Current Medications (20 questions)

### Active Medication List

11. **What medications is the patient currently taking?**

    - Expected: Metformin, Lisinopril, Atorvastatin, Levothyroxine
    - Use case: Medication reconciliation at visit start

12. **List all active medications with doses.**

    - Expected: Metformin 1000mg, Lisinopril 10mg, Atorvastatin 20mg, Levothyroxine 25mcg
    - Use case: Complete medication review

13. **Is the patient on any diabetes medications?**

    - Expected: Yes, Metformin 1000mg
    - Use case: Checking diabetes treatment status

14. **What blood pressure medication is prescribed?**

    - Expected: Lisinopril 10mg
    - Use case: Reviewing HTN therapy

15. **What cholesterol medication is the patient on?**
    - Expected: Atorvastatin 20mg
    - Use case: Checking lipid management

### Specific Medication Details

16. **What dose of Metformin is prescribed?**

    - Expected: 1000mg (or current dose)
    - Use case: Verifying current dose before potential adjustment

17. **When was Metformin started?**

    - Expected: August 2006
    - Use case: Understanding medication duration

18. **Has the Metformin dose changed?**

    - Expected: Yes, started at 500mg, increased to 1000mg in September 2006
    - Use case: Reviewing dose titration history

19. **What dose of Lisinopril is the patient on?**

    - Expected: 10mg
    - Use case: Checking current BP medication dose

20. **What thyroid medication is prescribed?**
    - Expected: Levothyroxine 25mcg
    - Use case: Verifying thyroid replacement therapy

### Medication History

21. **When were the current medications started?**

    - Expected: August 2006 (initial diagnosis)
    - Use case: Understanding treatment timeline

22. **Show me the medication history.**

    - Expected: Timeline of medication starts and changes
    - Use case: Reviewing past medication changes

23. **Has any medication been discontinued?**

    - Expected: Check for stopped medications
    - Use case: Understanding past medication trials

24. **When was the last medication change?**
    - Expected: Metformin increase September 2006 (or most recent change)
    - Use case: Timing for reassessment

### Medication Classes

25. **Is the patient on a statin?**

    - Expected: Yes, Atorvastatin
    - Use case: Quick check for guideline-based therapy

26. **Is the patient on an ACE inhibitor or ARB?**

    - Expected: Yes, Lisinopril (ACE inhibitor)
    - Use case: Checking renoprotective therapy

27. **Is the patient on insulin?**

    - Expected: No
    - Use case: Understanding diabetes regimen complexity

28. **Is the patient on anticoagulation?**

    - Expected: No
    - Use case: Bleeding risk assessment

29. **How many medications is the patient taking?**

    - Expected: 4 chronic medications
    - Use case: Assessing pill burden

30. **Is the patient on aspirin?**
    - Expected: Check medication list
    - Use case: Cardiovascular protection status

---

## Category 3: Laboratory Values & Trends (30 questions)

### Diabetes Monitoring

31. **What is the most recent HbA1c?**

    - Expected: Most recent HbA1c value with date
    - Use case: Assessing current diabetes control before visit

32. **When was the last HbA1c checked?**

    - Expected: Date of most recent HbA1c
    - Use case: Determining if HbA1c is due

33. **Show me all HbA1c values.**

    - Expected: Chronological list of HbA1c results
    - Use case: Reviewing diabetes control trend

34. **What was the HbA1c at diagnosis?**

    - Expected: 9.3% (August 2006)
    - Use case: Understanding baseline severity

35. **Has the HbA1c improved since starting treatment?**

    - Expected: Comparison of initial vs recent values
    - Use case: Assessing treatment response

36. **What was the most recent glucose level?**
    - Expected: Most recent glucose from labs
    - Use case: Point-in-time glucose assessment

### Complete Blood Count

37. **What was the most recent CBC?**

    - Expected: Most recent CBC panel results with date
    - Use case: Checking for anemia, infection, other abnormalities

38. **What is the hemoglobin level?**

    - Expected: Hemoglobin value from most recent CBC
    - Use case: Anemia check

39. **What is the white blood cell count?**

    - Expected: WBC from most recent CBC
    - Use case: Infection/inflammation assessment

40. **What is the platelet count?**

    - Expected: Platelet count from CBC
    - Use case: Bleeding risk assessment

41. **When was the last CBC done?**
    - Expected: Date of most recent CBC
    - Use case: Determining if labs are current

### Metabolic Panel

42. **What was the most recent comprehensive metabolic panel?**

    - Expected: Most recent CMP results
    - Use case: Kidney function, electrolytes, liver function review

43. **What is the creatinine level?**

    - Expected: Creatinine value from CMP
    - Use case: Kidney function assessment

44. **What is the estimated GFR?**

    - Expected: eGFR if calculated
    - Use case: Kidney function staging

45. **What are the liver enzymes?**

    - Expected: ALT, AST, alkaline phosphatase from CMP
    - Use case: Checking for medication effects on liver

46. **What is the glucose from the metabolic panel?**

    - Expected: Glucose from CMP
    - Use case: Fasting glucose assessment

47. **What are the electrolytes?**
    - Expected: Sodium, potassium, chloride, CO2
    - Use case: Electrolyte balance on diuretic therapy

### Lipid Panel

48. **What was the most recent lipid panel?**

    - Expected: Most recent lipid panel with date
    - Use case: Cholesterol management review

49. **What is the LDL cholesterol?**

    - Expected: LDL value from lipid panel
    - Use case: Assessing statin efficacy

50. **What is the HDL cholesterol?**

    - Expected: HDL value
    - Use case: Cardiovascular risk assessment

51. **What is the total cholesterol?**

    - Expected: Total cholesterol value
    - Use case: Overall lipid status

52. **What are the triglycerides?**

    - Expected: Triglyceride value
    - Use case: Lipid panel component

53. **When was the last lipid panel checked?**

    - Expected: Date of most recent lipid panel
    - Use case: Determining if lipids are due

54. **Show me the lipid trend.**
    - Expected: LDL, HDL, triglycerides over time
    - Use case: Assessing statin response

### Other Labs

55. **What was the most recent thyroid function test?**

    - Expected: TSH, free T4 if available
    - Use case: Thyroid replacement adequacy

56. **What is the TSH level?**

    - Expected: TSH value
    - Use case: Levothyroxine dose assessment

57. **Has kidney function changed over time?**

    - Expected: Creatinine trend
    - Use case: Monitoring for diabetic nephropathy

58. **Show me all laboratory results from the last visit.**

    - Expected: All labs from most recent encounter
    - Use case: Pre-visit chart review

59. **When were labs last checked?**

    - Expected: Date of most recent lab work
    - Use case: Planning for today's orders

60. **What labs were done at diagnosis?**
    - Expected: CBC, CMP, lipids, HbA1c from August 2006
    - Use case: Understanding baseline values

---

## Category 4: Vital Signs & Physical Measurements (15 questions)

### Blood Pressure

61. **What is the most recent blood pressure?**

    - Expected: Most recent BP reading with date
    - Use case: Quick BP status check

62. **What was the blood pressure at the last visit?**

    - Expected: BP from previous encounter
    - Use case: Comparing to today's reading

63. **Show me the blood pressure trend.**

    - Expected: Series of BP readings over time
    - Use case: Assessing BP control trajectory

64. **What was the blood pressure at diagnosis?**

    - Expected: 152/97 mm[Hg] (August 2006)
    - Use case: Understanding baseline severity

65. **Has blood pressure improved on medication?**
    - Expected: Comparison of pre- and post-treatment BPs
    - Use case: Assessing treatment efficacy

### Weight & BMI

66. **What is the patient's current weight?**

    - Expected: Most recent weight
    - Use case: Current weight for medication dosing

67. **What is the patient's height?**

    - Expected: Height measurement
    - Use case: BMI calculation verification

68. **What is the BMI?**

    - Expected: Current BMI value
    - Use case: Obesity classification

69. **Show me the weight trend.**

    - Expected: Weight values over time
    - Use case: Assessing weight loss/gain pattern

70. **What was the weight at diagnosis?**
    - Expected: Weight from August 2006
    - Use case: Baseline comparison

### Other Vital Signs

71. **What was the heart rate at the last visit?**

    - Expected: Heart rate from vitals
    - Use case: Cardiovascular assessment

72. **What was the temperature?**

    - Expected: Temperature from vitals
    - Use case: Fever check

73. **Are there any abnormal vital signs documented?**

    - Expected: List of out-of-range vitals
    - Use case: Quick scan for concerning values

74. **What vitals were recorded at the diagnosis visit?**

    - Expected: All vitals from August 2006
    - Use case: Baseline vital sign review

75. **When were vitals last recorded?**
    - Expected: Date of last vital signs
    - Use case: Currency of vital sign data

---

## Category 5: Imaging & Diagnostic Studies (12 questions)

### Imaging History

76. **Has the patient had any imaging studies?**

    - Expected: Yes/No with list if yes
    - Use case: Quick imaging history check

77. **What imaging studies are documented?**

    - Expected: Echocardiogram, fundus photo, ultrasound, chest X-ray
    - Use case: Complete imaging list

78. **When was the last imaging study?**

    - Expected: Date of most recent imaging
    - Use case: Currency of imaging data

79. **Show me all imaging from the last year.**
    - Expected: Recent imaging studies with dates
    - Use case: Recent imaging review

### Cardiac Imaging

80. **Has the patient had an echocardiogram?**

    - Expected: Yes (February 2007) or No
    - Use case: Cardiac imaging status

81. **When was the echocardiogram done?**

    - Expected: February 14, 2007
    - Use case: Timing for repeat echo

82. **What were the echo results?**
    - Expected: Echo findings if documented
    - Use case: Cardiac function review

### Diabetic Screening Imaging

83. **Has the patient had a fundus photograph?**

    - Expected: Yes (February 2007)
    - Use case: Diabetic retinopathy screening status

84. **When was the last eye imaging?**
    - Expected: Date of fundus photography
    - Use case: Determining if annual eye exam is due

### Other Imaging

85. **Has the patient had a chest X-ray?**

    - Expected: Yes (February 2007)
    - Use case: Pulmonary imaging status

86. **Has the patient had any abdominal imaging?**

    - Expected: Check for ultrasound or other abdominal studies
    - Use case: GI/renal imaging review

87. **When is the next imaging due?**
    - Expected: Based on last imaging dates and guidelines
    - Use case: Planning future studies

---

## Category 6: Visit History & Encounters (15 questions)

### Recent Visits

88. **When was the patient last seen?**

    - Expected: Date of most recent encounter
    - Use case: Understanding visit frequency

89. **What happened at the last visit?**

    - Expected: Summary of most recent encounter
    - Use case: Continuity of care

90. **When was the visit before that?**

    - Expected: Previous encounter date
    - Use case: Visit interval assessment

91. **How often has the patient been coming in?**

    - Expected: Visit frequency pattern
    - Use case: Adherence to follow-up plan

92. **Show me all visits in the last year.**
    - Expected: List of encounters in past 12 months
    - Use case: Recent visit history

### Key Historical Encounters

93. **When was the patient diagnosed with diabetes?**

    - Expected: August 20, 2006
    - Use case: Disease duration calculation

94. **What happened at the diagnosis visit?**

    - Expected: August 2006 - diagnosed with 5 conditions, started 4 medications, baseline labs
    - Use case: Understanding initial presentation

95. **What was done at the September 2006 visit?**

    - Expected: Metformin increased to 1000mg
    - Use case: Early treatment adjustment review

96. **What happened at the February 2007 visit?**
    - Expected: Imaging studies (echo, fundus, ultrasound, chest X-ray)
    - Use case: Imaging workup review

### Visit Patterns

97. **How many visits has the patient had total?**

    - Expected: 68 encounters
    - Use case: Understanding patient engagement

98. **When was the patient's first visit ever?**

    - Expected: Childhood visits from 1956+
    - Use case: Length of patient relationship

99. **Has the patient missed any appointments?**

    - Expected: Check for no-shows
    - Use case: Adherence assessment

100.  **What type of visit is due next?**

      - Expected: Based on last visit type and interval
      - Use case: Planning next encounter

101.  **Show me the encounter timeline.**

      - Expected: Chronological list of all encounters
      - Use case: Comprehensive visit history

102.  **Has the patient been to the emergency room?**
      - Expected: Check for ED visits
      - Use case: Acute event history

---

## Category 7: Procedures & Interventions (8 questions)

103. **What procedures have been done?**

     - Expected: List of documented procedures
     - Use case: Procedure history review

104. **When was the last physical examination?**

     - Expected: Date of most recent physical exam
     - Use case: Currency of exam

105. **Has the patient had a diabetic foot exam?**

     - Expected: Search for foot exam documentation
     - Use case: Diabetic complication screening status

106. **Has the patient had any surgeries?**

     - Expected: Surgical history
     - Use case: Past surgical interventions

107. **What screening procedures have been done?**

     - Expected: Preventive procedures (fundus photo, etc.)
     - Use case: Preventive care review

108. **When was the last eye exam?**

     - Expected: Most recent ophthalmology evaluation
     - Use case: Annual diabetic eye exam status

109. **Has the patient had a colonoscopy?**

     - Expected: Check for colonoscopy documentation
     - Use case: Age-appropriate cancer screening

110. **What procedures are documented in the last year?**
     - Expected: Recent procedures
     - Use case: Recent intervention review

---

## Category 8: Allergies & Adverse Reactions (5 questions)

111. **Does the patient have any documented allergies?**

     - Expected: Allergy list or "No known allergies"
     - Use case: Safe prescribing

112. **What medication allergies are documented?**

     - Expected: Drug allergy list
     - Use case: Avoiding contraindicated medications

113. **Are there any food allergies?**

     - Expected: Food allergy documentation
     - Use case: Dietary counseling safety

114. **What reactions has the patient had to medications?**

     - Expected: Adverse drug reaction history
     - Use case: Medication safety review

115. **Is there a sulfa allergy?**
     - Expected: Check for sulfa allergy
     - Use case: Antibiotic selection

---

## Category 9: Problem List & Active Issues (10 questions)

### Current Problems

116. **What is the current problem list?**

     - Expected: Active conditions list
     - Use case: Quick problem list review

117. **How many active diagnoses does the patient have?**

     - Expected: Count of active conditions
     - Use case: Complexity assessment

118. **What is the primary diagnosis?**

     - Expected: Main condition driving care
     - Use case: Visit focus identification

119. **Are all the conditions currently active?**

     - Expected: Active vs resolved status
     - Use case: Problem list accuracy

120. **What conditions are being actively managed?**
     - Expected: Conditions with ongoing treatment
     - Use case: Current management focus

### Problem Details

121. **What diabetes-related complications are documented?**

     - Expected: Check for neuropathy, retinopathy, nephropathy
     - Use case: Complication surveillance

122. **Are there any cardiovascular conditions?**

     - Expected: HTN, hyperlipidemia present; check for CAD, heart failure, etc.
     - Use case: Cardiac risk assessment

123. **Are there any respiratory conditions?**

     - Expected: Check for asthma, COPD, etc.
     - Use case: Pulmonary comorbidity review

124. **What endocrine conditions are documented?**

     - Expected: Diabetes, hypothyroidism
     - Use case: Endocrine problem review

125. **Has the patient had any strokes or TIAs?**
     - Expected: Check for cerebrovascular events
     - Use case: Neurologic history

---

## Category 10: Temporal Queries & Trends (20 questions)

### Disease Duration

126. **How long has the patient had diabetes?**

     - Expected: Years since August 2006 diagnosis
     - Use case: Disease duration for staging

127. **How long has the patient been hypertensive?**

     - Expected: Duration since HTN diagnosis
     - Use case: Chronicity assessment

128. **When did the chronic diseases start?**
     - Expected: August 2006 for all metabolic conditions
     - Use case: Understanding disease timeline

### Treatment Duration

129. **How long has the patient been on Metformin?**

     - Expected: Duration since August 2006
     - Use case: Medication longevity

130. **How long has the patient been on the current medication regimen?**
     - Expected: Time since last medication change
     - Use case: Stability of regimen

### Lab Trends

131. **How has HbA1c changed over time?**

     - Expected: HbA1c trend graph/values
     - Use case: Diabetes control trajectory

132. **Is the diabetes control improving, stable, or worsening?**

     - Expected: Trend interpretation
     - Use case: Treatment efficacy assessment

133. **Show me the cholesterol trend.**

     - Expected: Lipid values over time
     - Use case: Statin response

134. **How has kidney function changed?**

     - Expected: Creatinine/eGFR trend
     - Use case: Nephropathy monitoring

135. **Compare the first and most recent HbA1c.**
     - Expected: 9.3% initial vs most recent
     - Use case: Overall treatment response

### Vital Sign Trends

136. **How has blood pressure trended since starting Lisinopril?**

     - Expected: BP values after medication start
     - Use case: Medication efficacy

137. **Has the patient's weight changed significantly?**

     - Expected: Weight change from baseline
     - Use case: Weight management assessment

138. **Show me BMI over time.**
     - Expected: BMI trend
     - Use case: Obesity management tracking

### Visit Frequency Trends

139. **How often has the patient been seen in the last year?**

     - Expected: Visit frequency in past 12 months
     - Use case: Engagement pattern

140. **When is the patient due for follow-up?**
     - Expected: Based on last visit and standard intervals
     - Use case: Scheduling planning

### Medication Timeline

141. **Show me when each medication was started.**

     - Expected: Medication start dates
     - Use case: Treatment timeline review

142. **What medication changes have occurred?**

     - Expected: History of medication adjustments
     - Use case: Treatment evolution understanding

143. **When was the last medication adjustment?**

     - Expected: Most recent medication change date
     - Use case: Timing for reassessment

144. **How long has it been since labs were checked?**

     - Expected: Time since last lab draw
     - Use case: Determining if labs are due

145. **What is the interval between HbA1c checks?**
     - Expected: Time between HbA1c measurements
     - Use case: Monitoring frequency assessment

---

## Category 11: Specific Data Retrieval (20 questions)

### Exact Value Lookups

146. **What was the exact HbA1c on August 20, 2006?**

     - Expected: 9.3%
     - Use case: Precise historical value

147. **What was the exact blood pressure on the diagnosis date?**

     - Expected: 152/97 mm[Hg]
     - Use case: Baseline severity documentation

148. **What was the LDL at diagnosis?**

     - Expected: 170 mg/dL
     - Use case: Pre-treatment lipid level

149. **What was the HDL at diagnosis?**

     - Expected: 38 mg/dL
     - Use case: Baseline HDL for comparison

150. **What was the BMI at diagnosis?**
     - Expected: 31.9 kg/m²
     - Use case: Baseline obesity severity

### Medication Specifics

151. **What is the exact dose and frequency of Metformin?**

     - Expected: Full prescription details (e.g., 1000mg PO daily)
     - Use case: Prescription verification

152. **What is the RxNorm code for the patient's statin?**

     - Expected: RxNorm code for Atorvastatin 20mg
     - Use case: E-prescribing

153. **When was Lisinopril first prescribed?**
     - Expected: Exact date of initial prescription
     - Use case: Medication timeline

### Lab Specifics

154. **What was the creatinine on [specific date]?**

     - Expected: Creatinine value from that encounter
     - Use case: Point-in-time kidney function

155. **What specific CBC values were abnormal?**

     - Expected: Out-of-range CBC components
     - Use case: Abnormality identification

156. **What was the glucose on the CMP?**
     - Expected: Specific glucose from metabolic panel
     - Use case: Fasting glucose vs HbA1c correlation

### Encounter Specifics

157. **What encounter types are documented?**

     - Expected: List of encounter classes (ambulatory, etc.)
     - Use case: Visit type review

158. **What was the reason for the [specific date] visit?**

     - Expected: Encounter reason/chief complaint
     - Use case: Understanding visit context

159. **Who was the provider at the last visit?**

     - Expected: Provider name if documented
     - Use case: Care continuity

160. **What location was the last visit at?**
     - Expected: Visit location if documented
     - Use case: Care setting awareness

### Dates & Timing

161. **What is the exact date of diabetes diagnosis?**

     - Expected: August 20, 2006
     - Use case: Precise disease onset

162. **When exactly was the Metformin dose increased?**

     - Expected: September 19, 2006 (or exact date)
     - Use case: Medication change timing

163. **What date were the imaging studies done?**

     - Expected: February 14, 2007
     - Use case: Imaging timeline

164. **When is the patient's birthday?**

     - Expected: Date of birth
     - Use case: Age verification, birthday card

165. **How many days ago was the last visit?**
     - Expected: Days since last encounter
     - Use case: Visit recency

---

## Category 12: Comparison & Analysis Queries (15 questions)

### Before/After Comparisons

166. **Compare labs before and after starting medications.**

     - Expected: Pre-treatment vs post-treatment lab values
     - Use case: Treatment efficacy assessment

167. **How much did HbA1c improve after starting Metformin?**

     - Expected: Change in HbA1c post-treatment
     - Use case: Medication response quantification

168. **Has blood pressure improved on Lisinopril?**

     - Expected: BP comparison pre/post Lisinopril
     - Use case: Antihypertensive efficacy

169. **Did cholesterol improve on Atorvastatin?**

     - Expected: Lipid comparison pre/post statin
     - Use case: Statin response assessment

170. **Compare the first visit to the most recent visit.**
     - Expected: Side-by-side comparison of data
     - Use case: Overall progress review

### Trend Analysis

171. **Are HbA1c values trending up or down?**

     - Expected: Direction of HbA1c trend
     - Use case: Diabetes control trajectory

172. **Is weight increasing or decreasing?**

     - Expected: Weight trend direction
     - Use case: Weight management effectiveness

173. **Are blood pressures improving over time?**

     - Expected: BP trend assessment
     - Use case: Hypertension control

174. **How much has weight changed since diagnosis?**

     - Expected: Weight delta from baseline
     - Use case: Weight change quantification

175. **What is the rate of HbA1c change?**
     - Expected: HbA1c change per unit time
     - Use case: Response rate assessment

### Multi-Parameter Comparisons

176. **Which lab values are improving and which are not?**

     - Expected: Categorization of improving vs stable vs worsening labs
     - Use case: Identifying what needs attention

177. **Are all vital signs in normal range?**

     - Expected: Vital sign status summary
     - Use case: Quick vital sign check

178. **Which conditions are well-controlled and which are not?**

     - Expected: Control status for each condition
     - Use case: Treatment priority identification

179. **Compare this patient's values to guideline targets.**

     - Expected: Actual vs target values (e.g., HbA1c 9.3% vs target <7%)
     - Use case: Gap to goal assessment

180. **What values are farthest from goal?**
     - Expected: Prioritized list of uncontrolled parameters
     - Use case: Treatment focus identification

---

## Category 13: Negative/Absence Queries (10 questions)

181. **Does the patient have heart failure?**

     - Expected: No (not documented)
     - Use case: Ruling out conditions

182. **Is there any history of MI?**

     - Expected: Check for myocardial infarction
     - Use case: Cardiac event history

183. **Does the patient have chronic kidney disease?**

     - Expected: Based on eGFR/creatinine
     - Use case: Renal comorbidity check

184. **Is there any cancer history?**

     - Expected: Check oncology conditions
     - Use case: Cancer screening/history

185. **Has the patient had any amputations?**

     - Expected: Check procedure history
     - Use case: Diabetic complication severity

186. **Are there any active infections documented?**

     - Expected: Check for infection diagnoses
     - Use case: Acute illness awareness

187. **Is there any history of diabetic ketoacidosis?**

     - Expected: Check for DKA events
     - Use case: Diabetes severity history

188. **Does the patient have peripheral vascular disease?**

     - Expected: Check for PVD diagnosis
     - Use case: Vascular complication screening

189. **Is there any liver disease documented?**

     - Expected: Check liver conditions
     - Use case: Medication safety (statin use)

190. **Has the patient had a coronary stent or bypass?**
     - Expected: Check procedure history
     - Use case: Cardiac intervention history

---

## Category 14: Multi-Resource Synthesis (10 questions)

### Cross-Resource Queries

191. **Which medications are for which conditions?**

     - Expected: Medication-condition mapping
     - Use case: Understanding treatment rationale

192. **What labs monitor what conditions?**

     - Expected: Lab-condition correlation
     - Use case: Monitoring plan review

193. **Show me all data from the diagnosis encounter.**

     - Expected: Conditions, vitals, labs, medications from August 2006
     - Use case: Comprehensive diagnosis visit review

194. **What has happened since the patient was diagnosed?**

     - Expected: Timeline of events since August 2006
     - Use case: Disease course summary

195. **Give me a complete picture of the patient's diabetes.**
     - Expected: Diabetes diagnosis, HbA1c values, medications, complications, screenings
     - Use case: Diabetes-focused comprehensive review

### Status Summaries

196. **Summarize the patient's cardiovascular risk factors.**

     - Expected: HTN, diabetes, hyperlipidemia, obesity status
     - Use case: CV risk assessment prep

197. **What screenings are documented for diabetic complications?**

     - Expected: Eye exams, foot exams, kidney monitoring
     - Use case: Preventive care review

198. **Give me the medication list with indications.**

     - Expected: Each med with its corresponding condition
     - Use case: Medication reconciliation with rationale

199. **What is being monitored and how often?**

     - Expected: Monitored parameters and frequency
     - Use case: Surveillance plan review

200. **Summarize what changed at the last visit.**
     - Expected: New labs, medication changes, new diagnoses from last encounter
     - Use case: Recent changes review
