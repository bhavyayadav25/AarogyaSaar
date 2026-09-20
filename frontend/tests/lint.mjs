import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve('src');
const files=[];
function walk(dir){for(const name of fs.readdirSync(dir)){const p=path.join(dir,name);const s=fs.statSync(p);if(s.isDirectory())walk(p);else if(/\.(js|jsx)$/.test(name))files.push(p)}}
walk(root);
const forbidden=[/patient@sih26047\.local/i,/doctor@sih26047\.local/i,/Rahul Sharma/i,/Dr\. Ananya Verma/i,/consultation_id\s*[:=]\s*[0-9]+/i,/encounter_id\s*[:=]\s*[0-9]+/i,/fetch\s*\(/i];
for(const p of files){const text=fs.readFileSync(p,'utf8');if(/client\.js$/.test(p))continue;for(const re of forbidden.slice(0,-1)){if(re.test(text))throw new Error(`Forbidden hardcoded clinical/demo data in ${p}: ${re}`)}if(/fetch\s*\(/.test(text))throw new Error(`Raw fetch found outside centralized API client: ${p}`)}
console.log(`Frontend policy lint passed: ${files.length} JS/JSX files checked.`);
