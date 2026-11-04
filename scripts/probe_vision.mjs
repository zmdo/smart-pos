// Probe DeepSeek-V4.1-Flash (deepseek-flash) vision + JSON orientation output.
import { readFileSync } from 'node:fs';

const key = process.argv[2];
const imgPath = process.argv[3];
const b64 = readFileSync(imgPath).toString('base64');
const dataUrl = `data:image/jpeg;base64,${b64}`;

const sys = `你是一名人物朝向判别助手。只输出 JSON，不要输出解释，不要使用 markdown 代码块。
JSON 格式：
{"has_person": true/false, "orientation": "front|back|left|right|unknown", "face": {"visible": true/false, "bbox": [x1,y1,x2,y2] 或 null}, "confidence": 0-1}
bbox 使用 0-1000 归一化坐标，左上角为 (0,0)，右下角为 (1000,1000)，只框住人脸（不含头发外的身体）。`;

const body = {
  model: 'deepseek-flash',
  messages: [
    { role: 'system', content: sys },
    {
      role: 'user',
      content: [
        { type: 'image_url', image_url: { url: dataUrl, detail: 'high' } },
        { type: 'text', text: '判断图中人物的朝向（相对镜头）：正面/背面/左侧/右侧，并给出人脸框。只输出 JSON。' },
      ],
    },
  ],
  max_tokens: 300,
  temperature: 0,
  response_format: { type: 'json_object' },
};

const t0 = Date.now();
const res = await fetch('https://api.deepseek.com/chat/completions', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${key}` },
  body: JSON.stringify(body),
});
const text = await res.text();
console.log('status', res.status, 'ms', Date.now() - t0);
try {
  const j = JSON.parse(text);
  console.log(JSON.stringify(j.choices?.[0]?.message ?? j, null, 2).slice(0, 2000));
} catch {
  console.log(text.slice(0, 2000));
}
