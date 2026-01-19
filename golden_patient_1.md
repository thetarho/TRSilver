# Golden Patient Profile: Serafina151 Kellye282 Lesch175

## Patient Overview

- **Story Arc:** Healthy childhood → Adult onset of metabolic syndrome → Chronic disease management
  > "Patient t201 is a 69-year-old diabetic with hypertension and high cholesterol, diagnosed in 2006, on 4 chronic medications. Her data demonstrates all our query types: active meds, recent labs, imaging studies, and conditions."

---

## Timeline: The Clinical Progression

### Phase 1: Childhood (1956-1970s) - 60 encounters, mostly empty ✅

**What happened:** Routine well-child visits

**Clinical data:** None (realistic - healthy kid, no issues)

**Why empty:** Background encounters for continuity, no disease modules triggered

**Demo talking point:**

> "Notice how real EHRs have many visits with minimal data - this is normal"

---

### Phase 2: The Diagnosis (August 20, 2006) - Encounter t13315725 💥

**The Story:** 50-year-old woman comes in feeling tired, thirsty, gaining weight

#### What we find:

**5 Conditions diagnosed:**

- Type 2 Diabetes (HbA1c: 9.3% - poorly controlled)
- Essential Hypertension (BP: 152/97 - Stage 2)
- Hyperlipidemia (LDL: 170, HDL: 38)
- Hypothyroidism
- Obesity (BMI: 31.9)

**69 Observations (vitals + comprehensive labs):**

- CBC panel
- Comprehensive Metabolic Panel
- Lipid Panel
- HbA1c

**4 Medications started:**

- Metformin 500mg (diabetes)
- Lisinopril 10mg (blood pressure)
- Atorvastatin 20mg (cholesterol)
- Levothyroxine 25mcg (thyroid)

**3 DiagnosticReports:** Lab panels tagged as drCBC, drCMP, drLP

**2 Procedures:** Assessment procedures

#### Demo query examples:

- "Recent CBC?" → Returns complete blood count ✅
- "Patient's conditions?" → Returns 5 conditions with category "Encounter Diagnosis" ✅

---

### Phase 3: Follow-ups (Sept 2006 - Feb 2007) - 3 encounters with data

**Sept 19, 2006:** Check-up, adjust metformin to 1000mg

**Nov 16, 2006:** Problem visit, continue monitoring

**Feb 14, 2007:** Check-up with imaging studies (echo, fundus photo, ultrasound, chest X-ray)

**Demo talking point:**

> "These encounters show ongoing chronic disease management - new labs, medication adjustments"

---

### Phase 4: Maintenance (May 2007+) - 3 encounters with minimal data

**May 15, 2007:** Quick medication refill (1 resource)

**Aug 26, 2007:** Another refill (1 resource)

**Nov 24, 2007:** Routine check (1 resource)

- ✅ **Rich encounters demonstrate features** - 8 encounters have comprehensive data
- ✅ **All query types work** - medications, conditions, labs, imaging all return correct data
- ✅ **6 backend compatibility fixes applied** - medicationCodeableConcept, dr_subtype tags, category text, XML escaping, Provenance removal
- ✅ **Clinical notes generated** - All 68 encounters have SOAP-format Composition notes
