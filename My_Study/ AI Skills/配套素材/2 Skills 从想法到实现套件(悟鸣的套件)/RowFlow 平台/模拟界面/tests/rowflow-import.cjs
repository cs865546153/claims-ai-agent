const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..');
const example=fs.readFileSync(path.join(root,'examples/inventory_replenishment.groovy'),'utf8');
const reports=path.join(root,'.spec-to-ship/rowflow-import');
const shots=path.join(reports,'screenshots');fs.mkdirSync(shots,{recursive:true});
const cases=[],errors=[],requests=[];
const pass=(name,evidence)=>{cases.push({name,result:'pass',evidence});console.log('PASS '+name);};
let browser,page;
async function main(){
 browser=await chromium.launch({headless:true});
 page=await browser.newPage({viewport:{width:1440,height:1080},deviceScaleFactor:1});
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/^https?:/.test(r.url()))requests.push(r.url());});
 await page.goto(pathToFileURL(path.join(root,'rowflow-demo.html')).href);
 const result=async()=>JSON.parse(await page.locator('#resultJson').textContent());
 const open=async()=>{await page.locator('#importBtn').click();await page.locator('#importModal').waitFor({state:'visible'});};
 const paste=async(code,name='ai_generated.groovy')=>{await open();await page.locator('#importFilename').fill(name);await page.locator('#importCode').fill(code);await page.locator('#confirmImport').click();};
 const run=async()=>{await page.locator('#runBtn').click();await page.waitForFunction(()=>!document.getElementById('runBtn').disabled);};

 await open();await page.locator('#confirmImport').click();assert.match(await page.locator('#importFeedback').textContent(),/选择文件或粘贴/);assert.equal(await page.locator('#scenarioSelect').inputValue(),'city');
 await page.locator('#importFilename').fill('broken.groovy');await page.locator('#importCode').fill("pipeline(name:'broken',dslVersion:'1.0') {");await page.locator('#confirmImport').click();assert.match(await page.locator('#importFeedback').textContent(),/RF-DEMO-SYNTAX/);assert.equal(await page.locator('#scenarioSelect').inputValue(),'city');await page.locator('#closeImport').click();
 pass('UI-08 空内容与解析失败不覆盖原场景','错误在对话框展示，原城市分析和结果保持');

 await open();await page.locator('#scriptFile').setInputFiles(path.join(root,'examples/inventory_replenishment.groovy'));await page.waitForFunction(()=>document.getElementById('importFeedback').textContent.includes('已读取'));await page.locator('#confirmImport').click();await page.locator('#importModal').waitFor({state:'hidden'});
 assert.equal(await page.locator('#scenarioSelect').inputValue(),'imported');assert.equal(await page.locator('.imported-node').count(),10);assert.equal(await page.locator('.graph-links>path').count(),9);assert.deepEqual((await result()).map(x=>x.estimatedCost),[3216.6,1506.3]);assert.equal(await page.locator('#fixtureSelect').isDisabled(),true);
 pass('UI-08 / UI-12 实际文件导入与新场景','UTF-8 .groovy 文件生成 10 节点、9 条依赖边，预算 3216.60 / 1506.30');

 await page.locator('[data-node="enrich"]').click();assert.match(await page.locator('#codeInput').inputValue(),/\.join\(products/);assert.match(await page.locator('#editorStatus').textContent(),/原文件第/);assert.equal(await page.locator('#resultStep').isVisible(),true);await page.locator('[data-snapshot="right"]').click();assert.match(await page.locator('#resultStep').innerText(),/机械键盘/);await page.locator('[data-snapshot="input"]').click();assert.match(await page.locator('#resultStep').innerText(),/safetyStock/);await page.locator('[data-snapshot="output"]').click();assert.match(await page.locator('#resultStep').innerText(),/unitPrice/);
 await page.locator('[data-node="warehouse_groups"]').click();assert.match(await page.locator('#rowStage').textContent(),/GroupedRows/);assert.match(await page.locator('#resultStep').textContent(),/分组描述/);
 pass('UI-10 每个节点的源码、左右输入与输出','join 源码及原行号；右侧 4 条商品；分组明确为 GroupedRows 摘要');

 await run();assert.match(await page.locator('#runState').textContent(),/SUCCEEDED/);assert.match(await page.locator('#resultLogs').textContent(),/products \(from\)/);assert.match(await page.locator('#resultLogs').textContent(),/2 次/);assert.equal(await page.locator('#historyCount').textContent(),'1');await page.locator('#stepBtn').click();assert.equal(await page.locator('[data-node="products"]').getAttribute('aria-pressed'),'true');assert.match(await page.locator('#runState').textContent(),/单步 1 \/ 10/);await page.locator('#stepBtn').click();assert.equal(await page.locator('[data-node="inventory"]').getAttribute('aria-pressed'),'true');
 pass('UI-10 顺序运行、单步与记录','先读 join 右流 products，单步逐节点切换，执行日志及会话记录同步');

 await page.locator('#paramsBtn').click();await page.locator('#runtimeParams').fill('{');await page.locator('#applyParams').click();assert.equal(await page.locator('#paramsModal').isVisible(),true);assert.match(await page.locator('#paramsFeedback').getAttribute('class'),/is-error/);await page.locator('#runtimeParams').fill('{"minBudget":"2000"}');await page.locator('#applyParams').click();await page.locator('#paramsModal').waitFor({state:'hidden'});assert.equal((await result()).length,1);assert.equal((await result())[0].warehouse,'上海仓');
 pass('UI-11 参数校验与实际重算','非法 JSON 不生效；minBudget=2000 只保留上海仓');

 await page.locator('#fullTab').click();const doubled=example.replace("qty * r['unitPrice']","qty * r['unitPrice'] * 2");await page.locator('#codeInput').fill(doubled);assert.match(await page.locator('#flowGrid').textContent(),/旧图与快照已隐藏/);assert.match(await page.locator('#resultJson').textContent(),/代码已修改/);await run();assert.deepEqual((await result()).map(x=>x.estimatedCost),[6433.2,3012.6]);
 const downloading=page.waitForEvent('download');await page.locator('#downloadBtn').click();const download=await downloading;assert.equal(download.suggestedFilename(),'inventory_replenishment.groovy');assert.equal(fs.readFileSync(await download.path(),'utf8'),doubled);
 pass('UI-05 / UI-11 改表达式与完整导出','预算表达式乘二后输出 6433.20 / 3012.60；下载内容是修改后的完整文件');

 await page.locator('#fullTab').click();await page.locator('#codeInput').fill("pipeline(name:'unfinished',dslVersion:'1.0') {");await page.locator('#scenarioSelect').selectOption('city');await page.locator('#scenarioSelect').selectOption('imported');assert.match(await page.locator('#resultJson').textContent(),/RF-DEMO-SYNTAX/);assert.match(await page.locator('#flowGrid').textContent(),/旧图与快照已隐藏/);await page.locator('#resetCode').click();assert.equal((await result()).length,1);
 pass('UI-11 编辑失败后的切换与恢复','无效代码切换回来不会抛出未处理异常；恢复导入文本后仍保留显式运行参数');

 await paste(example.replace('"129.90"','"bad"'),'bad_price.groovy');await page.locator('#importModal').waitFor({state:'hidden'});assert.equal((await result()).code,'RF-TYPE-001');assert.equal((await result()).nodeId,'enrich');assert.match(await page.locator('[data-node="budget"]').textContent(),/上游失败/);await run();assert.match(await page.locator('#resultLogs').textContent(),/没有部分业务结果/);
 pass('UI-10 数据错误节点与下游阻断','错误在 enrich，不伪造预算或下游结果，最终无部分输出');

 const changedInput=example.replace('"stock": 3, "safetyStock": 10','"stock": 4, "safetyStock": 10');await open();const transfer=await page.evaluateHandle(({code})=>{const dt=new DataTransfer();dt.items.add(new File([code],'drag_inventory.groovy',{type:'text/plain'}));return dt;},{code:changedInput});await page.locator('#dropZone').dispatchEvent('drop',{dataTransfer:transfer});await page.waitForFunction(()=>document.getElementById('importFeedback').textContent.includes('已读取 drag_inventory'));await page.locator('#confirmImport').click();await page.locator('#importModal').waitFor({state:'hidden'});assert.equal((await result())[1].estimatedCost,1376.4);await transfer.dispose();
 pass('UI-08 / UI-11 拖放与输入改变','实际拖入 File，改库存后预算 1376.40，按新数据计算');

 const memory="pipeline(name: 'new_math_scene', dslVersion: '1.0') {\nsource('values',[type:'memory',rows:[[label:'A',qty:2,price:'0.10'],[label:'B',qty:3,price:'0.20']]])\ndef costs=from('values').map { r -> [label:r['label'],cost:r['qty']*decimal(r['price'])] }\nemit(costs)\n}\n";
 await paste('这里是 AI 生成的脚本：\n```groovy\n'+memory+'```\n预期金额是 0.20、0.60。','ai_math.groovy');await page.locator('#importModal').waitFor({state:'hidden'});assert.deepEqual(await result(),[{label:'A',cost:0.2},{label:'B',cost:0.6}]);assert.equal(await page.locator('.imported-node').count(),3);
 pass('UI-09 无注释新脚本与 AI 回复提取','未注册的文件名、变量与场景仍可解释；从唯一 Groovy 块提取，不执行回复里的结果说明');

 await paste(example.replace('"version": "1.0",','"version": "1.0", "expectedRows": [],'),'invalid_meta.groovy');assert.match(await page.locator('#importFeedback').textContent(),/RF-DEMO-META/);assert.equal((await result())[0].label,'A');await page.locator('#closeImport').click();
 await open();await page.locator('#scriptFile').setInputFiles({name:'bad.groovy',mimeType:'text/plain',buffer:Buffer.from([0xff,0xfe,0xfa])});await page.waitForFunction(()=>document.getElementById('importFeedback').textContent.includes('UTF-8'));assert.match(await page.locator('#importFeedback').getAttribute('class'),/is-error/);await page.locator('#closeImport').click();
 await open();await page.locator('#scriptFile').setInputFiles({name:'too_big.groovy',mimeType:'text/plain',buffer:Buffer.alloc(256*1024+1,32)});assert.match(await page.locator('#importFeedback').textContent(),/256 KiB/);await page.locator('#closeImport').click();
 pass('UI-08 / UI-09 编码、大小与伪造元数据校验','非法 UTF-8、超限和 expectedRows 被拒绝，当前已导入脚本未被覆盖');

 await paste(example,'inventory_classroom.groovy');await page.locator('#importModal').waitFor({state:'hidden'});await page.locator('[data-node="budget"]').click();await page.locator('[data-snapshot="output"]').click();await page.locator('#toast').evaluate(el=>el.classList.remove('visible'));await page.waitForTimeout(250);await page.screenshot({path:path.join(shots,'after-desktop.png'),fullPage:true,animations:'disabled'});
 const graphGeometry=[];for(const ratio of [0,.5,1]){const measured=await page.locator('#flowGrid').evaluate((el,ratio)=>{el.scrollLeft=(el.scrollWidth-el.clientWidth)*ratio;const node=el.querySelector('[data-node="budget"]'),canvas=el.querySelector('.graph-canvas');return{scroll:el.scrollLeft,relative:node.getBoundingClientRect().x-canvas.getBoundingClientRect().x,nodeLeft:parseFloat(node.style.left)};},ratio);assert.ok(Math.abs(measured.relative-measured.nodeLeft)<1);graphGeometry.push(measured);}
 pass('UI-07 / UI-10 图滚动和节点几何','起点、中点和终点滚动不改变节点相对画布坐标');

 await page.setViewportSize({width:390,height:844});await page.locator('#stepBtn').click();await page.waitForTimeout(250);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.screenshot({path:path.join(shots,'after-mobile.png'),fullPage:true,animations:'disabled'});await open();const box=await page.locator('#importModal').boundingBox();assert.ok(box.x>=0&&box.x+box.width<=391);const confirmBox=await page.locator('#confirmImport').boundingBox();assert.ok(confirmBox.y>=0&&confirmBox.y+confirmBox.height<=844);assert.equal(await page.locator('#scriptFile').inputValue(),'');await page.screenshot({path:path.join(shots,'import-dialog-mobile.png'),fullPage:false,animations:'disabled'});await page.locator('#closeImport').click();await page.locator('#paramsBtn').click();assert.equal(await page.locator('#runtimeParams').isVisible(),true);await page.locator('#closeParams').click();
 pass('UI-07 手机导入、图和参数弹窗','390×844，无页面横向溢出；图内滚动，导入和参数对话框在视口内');
 assert.deepEqual(errors,[]);assert.deepEqual(requests,[]);pass('全程离线且无未处理浏览器错误','所有脚本解析和计算在本地，不发送真实 HTTP/RPC/模型请求');
 fs.writeFileSync(path.join(reports,'browser-results.json'),JSON.stringify({status:'PASS',cases,errors,requests,graphGeometry},null,2));
 console.log('\n'+cases.length+' import checks passed.');
}
main().catch(async e=>{if(page)await page.screenshot({path:path.join(shots,'failure.png'),fullPage:true,animations:'disabled'}).catch(()=>{});fs.writeFileSync(path.join(reports,'browser-results.json'),JSON.stringify({status:'FAIL',cases,errors,requests,error:e.stack},null,2));console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();});
