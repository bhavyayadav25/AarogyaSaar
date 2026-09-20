import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const src=fs.readFileSync('src/api/client.js','utf8');
for(const endpoint of ['/api/auth/login','/api/auth/register','/api/encounters','/api/interview/questions','/api/interview/answer','/api/interview/complete','/api/ayush/questions','/api/ayush/answer','/api/ayush/complete','/api/documents/upload','/api/queue','/api/doctor/encounters/','/api/doctor/consultations/','/api/voice/speak','/api/voice/transcribe']) assert.ok(src.includes(endpoint),`missing integration ${endpoint}`);
assert.ok(src.includes("finalHeaders.Authorization = `Bearer ${token}`"));
assert.ok(src.includes("body instanceof FormData"));
test('frontend API contract map contains critical backend routes',()=>assert.ok(true));
