AarogyaSaar

AI-Assisted Multilingual OPD History-Taking and Clinical Handoff

From Patient Conversation to a Structured Clinical Case — Before Consultation

AarogyaSaar is a healthcare workflow prototype designed to improve the way patient information is collected and communicated before a doctor consultation.

It focuses on the pre-consultation stage of OPD care, where patients may struggle to explain their symptoms, medical history, or concerns clearly, while doctors may receive incomplete, unstructured, or time-consuming information.

AarogyaSaar provides a guided, multilingual patient interview and converts the collected information into a structured clinical handoff for the doctor.

⸻

Table of Contents

* Overview
* Problem Statement
* Our Solution
* Key Objectives
* Core User Roles
* Patient Workflow
* Doctor Workflow
* Multilingual Experience
* Clinical Handoff
* AYUSH and Allopathy Support
* System Architecture
* Technology Stack
* Project Structure
* Data Flow
* Backend
* Frontend
* Database and Source of Truth
* AI-Assisted Interview
* Speech and Voice Interaction
* Patient Consent
* Doctor Dashboard
* Safety and Clinical Boundaries
* Installation
* Running the Project
* Environment Variables
* Demo Data
* Testing the Prototype
* Recommended Demo Flow
* API Overview
* Accessibility
* Security and Privacy Considerations
* Current Prototype Scope
* Known Limitations
* Future Scope
* Research and Design Basis
* Smart India Hackathon Context
* Contributing
* License
* Disclaimer

⸻

Overview

AarogyaSaar is a prototype for patient case-taking software intended to support OPD workflows.

The system is designed around a simple idea:

Patients explain. AarogyaSaar structures. Doctors review.

Instead of expecting every patient to provide a complete and well-organized medical history independently, AarogyaSaar guides the patient through a structured interview.

The collected information is then organized into a clinical handoff that allows the doctor to quickly understand the patient’s reported concerns before beginning the consultation.

The system is designed particularly around challenges commonly encountered in public healthcare environments:

* Limited consultation time
* High OPD volumes
* Unstructured patient explanations
* Language barriers
* Difficulty documenting complete history
* Repetition of the same questions during consultation
* Variation in health literacy
* Difficulty communicating symptoms in a structured manner
* Need for a concise pre-consultation summary

AarogyaSaar is not intended to replace the doctor.

The doctor remains responsible for clinical interpretation, diagnosis, treatment decisions, and patient care.

⸻

Problem Statement

Patient Case-Taking Software

The first few minutes of a medical consultation are often spent understanding:

* What brought the patient to the hospital
* What symptoms they are experiencing
* When the symptoms started
* How the symptoms have changed
* Relevant medical history
* Medication information
* Previous conditions
* Allergies
* Relevant family or personal history
* Other concerns that may affect the consultation

In a busy OPD environment, collecting this information manually can become time-consuming and inconsistent.

Patients may also:

* Forget important details
* Explain symptoms in a non-linear manner
* Use local languages
* Have limited medical vocabulary
* Feel uncomfortable speaking directly about certain concerns
* Repeat information multiple times
* Not know which information is clinically relevant

This creates a gap between the patient’s story and the structured information required by the doctor.

AarogyaSaar addresses this gap through guided digital case-taking.

⸻

Our Solution

AarogyaSaar provides a pre-consultation workflow in which:

Patient
   ↓
Language Selection
   ↓
Consent
   ↓
Guided Interview
   ↓
Structured Patient Information
   ↓
Clinical Organization
   ↓
Doctor Handoff
   ↓
Doctor Review
   ↓
Consultation

The goal is not to make an automated diagnosis.

The goal is to make the patient’s information more structured, readable, and useful before the doctor begins the consultation.

⸻

Key Objectives

AarogyaSaar is designed around the following objectives:

1. Simplify patient history-taking

Use a guided one-question-at-a-time interaction rather than presenting a large medical form.

2. Support multilingual interaction

Allow patients to interact in a supported language instead of forcing the entire workflow into English.

3. Reduce information fragmentation

Transform multiple patient responses into organized clinical sections.

4. Improve pre-consultation information visibility

Give doctors a concise overview before starting the consultation.

5. Preserve clinical responsibility

The system presents patient-provided information and AI-assisted organization without replacing physician judgment.

6. Support different medical workflows

The prototype accommodates both Allopathy and AYUSH-oriented history-taking pathways where applicable.

⸻

Core User Roles

The initial AarogyaSaar experience provides role selection for:

Patient

The patient completes the guided pre-consultation interview.

Main responsibilities:

* Select language
* Provide consent
* Answer questions
* Provide relevant medical information
* Review collected information where applicable
* Complete the interview

⸻

Doctor

The doctor reviews the information collected before consultation.

Main responsibilities:

* Review patient identity
* Review encounter information
* Read the clinical brief
* Review symptoms and history
* Review safety/red-flag information
* Review documents
* Start consultation
* Add clinical notes and follow-up information

⸻

Hospital Administrator

The prototype also provides a role entry point for hospital administration workflows.

Administrative functionality can be extended independently from the patient and doctor workflows.

⸻

Patient Workflow

The intended patient flow is:

Open AarogyaSaar
        ↓
Select Patient
        ↓
Login / Patient Identification
        ↓
Select Language
        ↓
Consent
        ↓
Start / Continue Consultation
        ↓
Guided Interview
        ↓
Symptoms and History
        ↓
Medical History
        ↓
Relevant Additional Information
        ↓
Review / Completion
        ↓
Clinical Handoff Generated

The patient experience is intentionally designed to avoid overwhelming users with a large form.

Instead, information is collected progressively.

⸻

Doctor Workflow

The doctor workflow focuses on information density and rapid scanning.

The doctor can review:

* Patient identity
* Patient ID
* Encounter ID
* Department
* Visit type
* Preferred language
* Chief concern
* Symptoms
* Relevant history
* Patient-provided information
* Safety/red-flag information
* Documents
* Structured clinical brief

The doctor can then proceed to:

Start Consultation

The clinical brief is intended to provide a fast overview while still allowing the doctor to inspect the underlying patient information.

⸻

Multilingual Experience

Multilingual interaction is a core part of AarogyaSaar.

The prototype supports patient interaction in:

* English
* Hindi — हिन्दी
* Bangla — বাংলা

The selected language is intended to control the patient-facing interaction rather than simply translating a single screen.

This includes, where supported by the implementation:

* Patient interface text
* Interview questions
* Patient responses
* Validation messages
* Error messages
* Confirmation messages
* Medical-history categories
* Patient-facing summaries
* AI-assisted interview responses
* Speech recognition language
* Text-to-speech language where enabled

English remains available as the default/common interface language.

⸻

Clinical Handoff

One of AarogyaSaar’s central concepts is the clinical handoff.

The patient’s answers should not reach the doctor as a long unstructured conversation transcript.

Instead, information is organized into clinically useful sections.

A typical handoff may include:

PATIENT
├── Patient identity
├── Encounter information
└── Visit context
PRESENTING CONCERN
├── Chief concern
├── Symptoms
└── Duration / progression
HISTORY
├── Relevant medical history
├── Medication information
├── Allergies
└── Other relevant history
ADDITIONAL INFORMATION
├── Documents
├── Patient-reported concerns
└── Other collected information
SAFETY
└── Relevant reported red flags / safety information
CLINICAL BRIEF
└── Concise structured overview for physician review

The handoff is intended to help the doctor understand what the patient reported before beginning the consultation.

⸻

AYUSH and Allopathy Support

AarogyaSaar’s workflow is designed to accommodate different consultation pathways.

The prototype includes support for:

* Allopathy-oriented history-taking
* AYUSH-oriented history-taking

Where applicable, questions and selectable cards can differ based on the selected consultation pathway.

The system should not merge clinically different workflows simply to make the interface look uniform.

The underlying patient information remains the source material for the resulting handoff.

⸻

System Architecture

At a high level, AarogyaSaar follows a frontend-backend architecture.

                 ┌─────────────────────┐
                 │      Patient        │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │   AarogyaSaar UI    │
                 │     Frontend        │
                 └──────────┬──────────┘
                            │
                       API Requests
                            │
                            ▼
                 ┌─────────────────────┐
                 │      Backend        │
                 │   Clinical Logic    │
                 │   AI Integration    │
                 │   Data Handling     │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │       Database      │
                 │ Patient / Encounter │
                 │ Interview / Handoff │
                 └─────────────────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │    Doctor Dashboard │
                 └─────────────────────┘

The backend/database should remain the source of truth for persistent patient and encounter information.

The frontend should not depend on hardcoded patient information for the actual workflow.

⸻

Technology Stack

The prototype is structured around:

Frontend

* React-based frontend
* Vite development/build tooling
* Modern component-based UI
* Browser-based patient and doctor workflows
* Responsive interface

Backend

* Python backend
* FastAPI
* Uvicorn
* REST-style API communication

AI / Intelligence Layer

Used for:

* Guided conversational questioning
* Structuring collected information
* Generating a concise clinical brief
* Multilingual conversational support where configured

Speech Layer

Browser speech capabilities and/or configured speech processing services can be used for voice interaction.

Database

Persistent storage is used for:

* Patients
* Encounters
* Interviews
* Responses
* Clinical handoff information
* Other workflow state

The exact database/provider configuration should be taken from the project’s environment/configuration rather than hardcoded into this README.

⸻

Project Structure

A typical project structure is:

AarogyaSaar/
│
├── frontend/
│   ├── src/
│   ├── public/
│   ├── package.json
│   ├── vite.config.*
│   └── ...
│
├── backend/
│   ├── ...
│   ├── requirements.txt
│   └── ...
│
├── README.md
└── ...

The exact structure may vary depending on the current implementation.

Do not create a second frontend or duplicate application structure when modifying the existing prototype.

⸻

Data Flow

The intended information flow is:

Patient Login
      ↓
Patient Record
      ↓
Encounter
      ↓
Interview Session
      ↓
Question
      ↓
Patient Response
      ↓
Structured Interview Data
      ↓
Clinical Organization
      ↓
Clinical Handoff
      ↓
Doctor Dashboard

A key design principle is:

Patient → Encounter → Interview → Handoff

This relationship should remain consistent throughout the application.

⸻

Backend

The backend provides the application services required by the frontend.

Responsibilities include:

* Patient data retrieval
* Encounter management
* Interview state
* Question/response processing
* Persistence
* Handoff generation
* AI service integration
* Validation
* API responses

The backend runs using Uvicorn during local development.

⸻

Frontend

The frontend contains the patient, doctor, and administrative experiences.

The patient interface prioritizes:

* Large readable controls
* Simple navigation
* One question at a time
* Clear language selection
* Clear consent
* Minimal cognitive load
* Accessible interaction
* Clear completion state

The doctor interface prioritizes:

* Information density
* Fast scanning
* Clinical hierarchy
* Patient identification
* Concise summary
* Safety information
* Documents
* Consultation actions

⸻

Database and Source of Truth

AarogyaSaar should maintain a clear separation between UI state and persistent clinical workflow data.

The database should be treated as the source of truth for persistent information.

For example:

Patient
   │
   └── Encounter
          │
          └── Interview
                 │
                 ├── Questions
                 ├── Answers
                 └── Structured Data
                          │
                          └── Doctor Handoff

This is important because the consultation should not lose previously collected information simply because the frontend page is refreshed or the user enters the consultation again.

⸻

AI-Assisted Interview

The AI layer is intended to assist with the conversation and organization of information.

The system can:

1. Ask an appropriate question.
2. Receive the patient’s response.
3. Interpret the response for workflow purposes.
4. Determine what additional information may be needed.
5. Continue the interview.
6. Organize collected information.
7. Generate a structured clinical brief.

The AI should not independently establish a diagnosis merely from the patient’s responses.

⸻

AI Design Principle

The system follows a history-taking and information-structuring model rather than an autonomous diagnosis model.

Conceptually:

Patient says:
"I have been having stomach pain for three days."
        ↓
System collects:
- Complaint
- Duration
- Relevant follow-up information
        ↓
Doctor receives:
Structured patient-reported information

The clinical interpretation remains with the doctor.

⸻

Speech and Voice Interaction

Voice interaction is intended to reduce the burden of typing for patients.

The workflow may involve browser speech-recognition capabilities or another configured speech-processing mechanism.

A speech interaction can conceptually follow:

Patient speaks
      ↓
Microphone input
      ↓
Speech recognition
      ↓
Transcript
      ↓
Answer state
      ↓
Interview processing

The application should handle:

* Microphone permission
* Speech recognition start
* Speech recognition results
* Recognition completion
* Recognition errors
* Empty transcripts
* Unsupported browser behavior
* Language-specific recognition

The application should never depend on a voice button that does not provide a functional interaction.

Where voice input is unavailable, text input should remain an accessible fallback.

⸻

Patient Consent

Consent is an explicit part of the patient workflow.

Before collecting relevant information, the patient should be shown a clear consent step explaining that:

* The patient is participating in a digital history-taking process.
* Information provided will be used for the healthcare workflow.
* The system assists with organizing information.
* The doctor remains responsible for clinical decisions.
* The patient should provide information as accurately as possible.

Consent should be represented as part of the actual workflow state rather than being merely decorative UI text.

⸻

Doctor Dashboard

The doctor dashboard is designed around the principle:

The doctor should understand the patient quickly without losing access to the underlying information.

Important sections include:

Patient Identity

* Patient name
* Patient ID
* Encounter ID
* Department
* Visit type
* Language

30-Second Clinical Brief

A concise overview of the patient’s reported information.

Safety / Red Flags

Relevant safety information identified from the patient’s responses should be clearly separated from general history.

Documents

Relevant patient documents can be surfaced alongside the clinical information.

Consultation

The doctor can proceed to:

* Start Consultation
* Add notes
* Record follow-up information
* Perform the actual clinical assessment

⸻

Safety and Clinical Boundaries

AarogyaSaar is a clinical workflow assistance prototype, not an autonomous medical decision-maker.

The system should distinguish between:

Patient-reported information

What the patient actually stated.

AI-organized information

Information structured or summarized from the patient’s responses.

Clinical interpretation

The doctor’s responsibility.

The system should avoid presenting an AI-generated inference as an established diagnosis.

For example, the system should not turn:

“Patient reports chest discomfort.”

into:

“Patient has cardiac disease.”

unless a qualified clinician has actually made that diagnosis.

Similarly, the system should not invent:

* Diagnoses
* Medication history
* Severity
* Test results
* Allergies
* Symptoms
* Clinical findings

that were not supplied by the patient or clinician.

⸻

Installation

Prerequisites

Before running the project locally, install:

* Node.js
* npm
* Python 3
* pip
* Git

Verify installations:

node --version
npm --version
python3 --version
pip3 --version

⸻

Running the Project

AarogyaSaar contains separate frontend and backend applications.

1. Start the Backend

Open Terminal:

cd ~/Desktop/AarogyaSaar/backend

Create/activate the Python environment if the project uses one.

Then install dependencies:

pip3 install -r requirements.txt

Start the backend:

uvicorn main:app --reload --host 0.0.0.0 --port 8000

The backend will be available at:

http://localhost:8000

FastAPI documentation is normally available at:

http://localhost:8000/docs

⸻

2. Start the Frontend

Open a second Terminal window:

cd ~/Desktop/AarogyaSaar/frontend

Install frontend dependencies if required:

npm install

Start the development server:

npm run dev -- --host 0.0.0.0 --port 5173

The frontend will normally be available at:

http://localhost:5173

⸻

Environment Variables

Any API keys, database credentials, AI service credentials, or other secrets should be stored in environment variables.

Example:

API_BASE_URL=
DATABASE_URL=
AI_API_KEY=

Do not commit real credentials to Git.

Use an environment template such as:

.env.example

to document required variables without exposing secret values.

⸻

Demo Data

The prototype can use controlled demonstration data for testing the complete workflow.

Demo data should represent the actual application relationships:

Patient
   ↓
Encounter
   ↓
Interview
   ↓
Answers
   ↓
Handoff

Demo records should be clearly distinguishable from real patient information.

Never commit real patient medical information, personally identifiable information, passwords, API keys, or other confidential healthcare data to the repository.

⸻

Testing the Prototype

A complete end-to-end test should verify the following.

Patient Flow

* Landing page loads
* Patient role can be selected
* Patient login works
* Language selection appears at the correct stage
* Selected language persists
* Consent step is visible
* Consent can be completed
* Consultation can start
* Questions load correctly
* Patient can answer questions
* Text input works
* Voice functionality works where supported
* Questions change according to workflow
* AYUSH/allopathy cards behave correctly
* Patient responses persist
* Completion state appears

Doctor Flow

* Doctor login works
* Patient queue loads
* Patient information is displayed
* Encounter information is displayed
* Clinical brief loads
* Patient-reported information is visible
* Safety information is clearly separated
* Documents are available where present
* Start Consultation works
* Previously collected information remains available

Multilingual Flow

For each supported language:

* Interface text changes
* Questions use selected language
* Responses are processed correctly
* Validation/error text is appropriate
* Voice recognition uses the appropriate language where supported
* Patient-facing summary/confirmation uses the selected language

⸻

Recommended Demo Flow

For an SIH demonstration, the prototype can be presented in the following order.

1. Landing Page

Show the AarogyaSaar entry point and role selection.

2. Patient

Select the patient workflow.

3. Language

Choose a supported Indian language.

4. Consent

Show the patient consent step.

5. Interview

Demonstrate the guided question-by-question experience.

Use a realistic patient scenario rather than random answers.

6. Completion

Complete the interview.

7. Doctor Dashboard

Switch to the doctor view.

Show:

* Patient identity
* Encounter
* 30-Second Clinical Brief
* Symptoms/history
* Safety information
* Documents

8. Consultation

Demonstrate that the doctor can proceed from the structured handoff into consultation.

The key story is:

Patient Conversation
        ↓
Structured Information
        ↓
Clinical Handoff
        ↓
Doctor Consultation

⸻

API Overview

The backend API is responsible for communicating between the frontend and persistent application state.

Typical API categories include:

Authentication
    ├── Patient login
    └── Doctor login
Patients
    ├── Patient details
    └── Patient history
Encounters
    ├── Create/retrieve encounter
    └── Encounter state
Interviews
    ├── Start interview
    ├── Get question
    ├── Submit answer
    └── Retrieve interview
Handoff
    ├── Generate/retrieve clinical brief
    └── Retrieve structured information
Consultation
    ├── Start consultation
    ├── Notes
    └── Follow-up

The exact endpoint names should be taken from the currently implemented backend rather than documented as assumed endpoints.

⸻

Accessibility

AarogyaSaar is designed for a broad patient population, including users who may have limited digital literacy.

The patient interface should prioritize:

* Large readable text
* Clear buttons
* High contrast
* Simple language
* One primary action at a time
* Visible focus states
* Keyboard navigation
* Reduced motion where appropriate
* Font scaling
* Minimal visual clutter
* Clear feedback after actions

The interface should avoid relying solely on:

* Color
* Small icons
* Hover states
* Complex navigation
* Long forms

⸻

Security and Privacy Considerations

Healthcare information can contain highly sensitive personal data.

A production implementation should therefore include appropriate security controls.

Important considerations include:

Authentication

Use secure authentication for patients, doctors, and administrators.

Authorization

Users should only be able to access information appropriate to their role.

Data Encryption

Sensitive data should be encrypted during transmission and appropriately protected at rest.

Secret Management

API keys and credentials must never be stored directly in source code.

Auditability

Production systems should maintain appropriate audit logs for access and modification of clinical information.

Data Minimization

Only information required for the workflow should be collected and retained.

Patient Privacy

Real patient data should never be used in development or demonstrations without appropriate authorization and safeguards.

⸻

Current Prototype Scope

The current AarogyaSaar prototype focuses primarily on:

* Patient onboarding
* Role selection
* Patient authentication
* Language selection
* Consent
* Guided history-taking
* Multilingual patient interaction
* Patient response collection
* Structured information
* Clinical handoff
* Doctor dashboard
* 30-Second Clinical Brief
* Safety/red-flag presentation
* Document presentation
* Consultation transition
* AYUSH/Allopathy workflow support
* AI-assisted information organization

The prototype demonstrates the intended workflow and product experience.

It should not be interpreted as a production-ready hospital information system.

⸻

Known Limitations

As a prototype, AarogyaSaar has limitations.

These may include:

* Speech recognition can depend on browser support and microphone permissions.
* AI-generated content requires validation.
* Multilingual quality may vary between languages and medical terminology.
* Prototype authentication is not equivalent to production-grade identity management.
* Demo data is not equivalent to real hospital data.
* Production deployment requires stronger security and compliance controls.
* Clinical summaries should always be reviewed by a qualified healthcare professional.
* The prototype does not replace diagnosis, treatment, or physician judgment.

⸻

Future Scope

Potential future development areas include:

Hospital Integration

Integration with existing hospital information systems and electronic medical record systems.

FHIR / Health Data Standards

Support for standardized healthcare data exchange.

Advanced Indian Language Support

Expansion to additional Indian languages and regional language variants.

Improved Speech Recognition

Medical-domain speech recognition optimized for Indian accents and multilingual conversations.

Offline / Low-Connectivity Support

Support for environments with unreliable internet connectivity.

Hospital Queue Integration

Integration with OPD registration and queue management.

Clinical Document Integration

More extensive support for:

* Lab reports
* Prescriptions
* Imaging reports
* Previous consultation documents

Analytics

Aggregated operational analytics for hospitals, subject to appropriate privacy safeguards.

Human-in-the-Loop AI

More explicit clinician review and correction of AI-generated structured information.

⸻

Research and Design Basis

The product direction is informed by research and established concepts in areas including:

* Clinical history-taking
* Human-computer interaction
* Conversational interfaces
* Digital health
* Multilingual healthcare communication
* Clinical decision-support boundaries
* Speech interfaces
* Healthcare information structuring

Research references used by the project should be maintained separately in the project’s presentation/research documentation and linked here when the final citation list is fixed.

⸻

Smart India Hackathon Context

Smart India Hackathon 2026

Project: AarogyaSaar

Problem Statement: Patient Case-Taking Software

Problem Statement ID: SIH26047

Team ID: 125127

AarogyaSaar addresses the pre-consultation information collection problem through a multilingual, guided, AI-assisted patient case-taking workflow.

The prototype demonstrates how patient conversation can be converted into structured information that is easier for a doctor to review before consultation.

⸻

Design Philosophy

AarogyaSaar intentionally follows three principles:

For the Patient

Simple. Clear. Accessible.

The patient should not need medical or technical expertise to use the system.

For the Doctor

Structured. Concise. Clinically useful.

The doctor should be able to scan the important information quickly while retaining access to the underlying patient responses.

For the System

Assist, don’t replace.

AI is used to assist with information collection and organization.

Clinical decisions remain with healthcare professionals.

⸻

Contributing

If extending the prototype:

1. Work within the existing frontend and backend.
2. Avoid creating parallel implementations of existing workflows.
3. Keep the backend/database as the source of truth.
4. Avoid hardcoded clinical information.
5. Avoid inventing diagnoses or patient information.
6. Preserve existing patient → encounter → interview relationships.
7. Test both patient and doctor workflows after changes.
8. Test English and supported multilingual workflows.
9. Test the application after page refreshes and state transitions.
10. Keep API changes synchronized with frontend usage.
11. Never commit secrets or real patient data.

⸻

Development Principles

When making changes to AarogyaSaar:

DO
✓ Modify the existing application
✓ Reuse existing components
✓ Reuse existing APIs
✓ Preserve existing data relationships
✓ Validate real workflow state
✓ Test patient + doctor flows
✓ Keep clinical information grounded in source data
DO NOT
✗ Create a second frontend
✗ Create fake APIs
✗ Hardcode patient records
✗ Invent diagnoses
✗ Invent medications
✗ Replace backend data with frontend mock data
✗ Break existing navigation
✗ Remove persistent interview state
✗ Treat AI output as confirmed clinical diagnosis

⸻

Disclaimer

AarogyaSaar is an academic/prototype healthcare software project created to demonstrate an AI-assisted multilingual patient case-taking and clinical handoff workflow.

It is not a substitute for professional medical advice, diagnosis, treatment, or clinical judgment.

Information generated or organized by the system must be reviewed by an appropriately qualified healthcare professional before being used for clinical decision-making.

The prototype should not be used with real patient data in a production healthcare environment without appropriate security, privacy, regulatory, clinical validation, and institutional approvals.

⸻

AarogyaSaar

Every Voice. Every Patient.

Patient Conversation → Structured Clinical Case → Doctor Consultation

⸻