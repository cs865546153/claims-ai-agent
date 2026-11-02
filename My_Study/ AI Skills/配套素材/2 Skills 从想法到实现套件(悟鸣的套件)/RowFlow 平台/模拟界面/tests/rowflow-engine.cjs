const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const Engine=require('../lib/rowflow-engine');
const root=path.resolve(__dirname,'..');
const read=name=>fs.readFileSync(path.join(root,name),'utf8');
const blocks=(name,language)=>[...read(name).matchAll(new RegExp('^```'+language+'\\n([\\s\\S]*?)^```','gm'))].map(m=>m[1]);
const fixtures=blocks('10-示例数据与服务契约.md','json').map(JSON.parse);
const scripts=blocks('11-完整脚本示例.md','groovy');
const expected=blocks('11-完整脚本示例.md','json').map(JSON.parse);
const catalog=(c,q)=>c.type==='http'?{data:{items:fixtures[0]}}:c.method==='listUsers'?{data:{users:fixtures[1]}}:{data:fixtures[1].find(u=>u.userId===q.userId)??null};
const example=read('examples/inventory_replenishment.groovy');
const expectedInventory=[{warehouse:'上海仓',skuCount:2,replenishQty:7,estimatedCost:3216.6},{warehouse:'杭州仓',skuCount:2,replenishQty:10,estimatedCost:1506.3}];
const cases=[];
function test(name,fn){fn();cases.push(name);console.log('PASS '+name);}
function wrap(body,config=''){return `pipeline(name: 'test_pipeline', dslVersion: '1.0'${config}) {\n${body}\n}`;}
function memory(rows,chain='from(\'rows\')',config=''){return wrap(`source('rows', [type:'memory', rows:${rows}])\ndef result=${chain}\nemit(result)`,config);}
function codeError(script,code){assert.throws(()=>Engine.run(script),e=>e.code===code);}

for(let i=0;i<scripts.length;i++)test('既有完整示例 E0'+(i+1),()=>{const r=Engine.run(scripts[i],{catalog});assert.equal(r.error,null);assert.deepEqual(r.rows,expected[i]);});
test('库存默认结果、依赖、快照与调用数',()=>{const r=Engine.run(example);assert.equal(r.error,null);assert.deepEqual(r.rows,expectedInventory);assert.equal(r.nodes.length,10);assert.equal(r.executionOrder[0],'products');assert.equal(r.nodes.find(n=>n.id==='low_stock').inputRows,7);assert.equal(r.nodes.find(n=>n.id==='low_stock').outputRows,4);assert.equal(r.nodes.find(n=>n.id==='enrich').rightRows,4);assert.equal(r.stats.sourceRequests,2);assert.deepEqual(r.nodes.find(n=>n.id==='warehouse_groups').rows,[{warehouse:'杭州仓',inputRows:2},{warehouse:'上海仓',inputRows:2}]);});
test('运行参数与注释默认参数会改变结果',()=>{assert.deepEqual(Engine.run(example,{params:{minBudget:'2000'}}).rows,[expectedInventory[0]]);assert.deepEqual(Engine.run(example.replace('"minBudget": "0"','"minBudget": "2000"')).rows,[expectedInventory[0]]);});
test('修改源记录，按新输入重算而非模板匹配',()=>{const script=example.replace('"stock": 3, "safetyStock": 10','"stock": 4, "safetyStock": 10');const r=Engine.run(script);assert.equal(r.error,null);assert.equal(r.rows[1].estimatedCost,1376.4);assert.equal(r.rows[1].replenishQty,9);});
test('修改业务表达式，预算真的翻倍',()=>{const r=Engine.run(example.replace("qty * r['unitPrice']","qty * r['unitPrice'] * 2"));assert.equal(r.error,null);assert.equal(r.rows[0].estimatedCost,6433.2);assert.equal(r.rows[1].estimatedCost,3012.6);});
test('去掉节点注释并重命名变量也能解释',()=>{const r=Engine.run(example.replace(/^\s*\/\/ @step.*$/gm,'').replace(/\blowStock\b/g,'shortages').replace(/\bbudgeted\b/g,'calculatedRows'));assert.equal(r.error,null);assert.deepEqual(r.rows,expectedInventory);assert.equal(r.nodes.length,10);});
test('不同的纯内存脚本支持新算式与筛选',()=>{const script=memory("[[id:'A',qty:2,price:'0.10'],[id:'B',qty:3,price:'0.20']]","from('rows').withFields { r -> [cost:r['qty']*decimal(r['price'])] }.filter { r -> r['cost'] > 0.30G }.select('id','cost')");const r=Engine.run(script);assert.equal(r.error,null);assert.deepEqual(r.rows,[{id:'B',cost:0.6}]);});
test('decimal 精确算术与 HALF_UP 平均值',()=>{const r=Engine.run(memory("[[v:'0.10'],[v:'0.20']]","from('rows').aggregate([total:sum { r -> decimal(r['v']) }, average:avg { r -> decimal(r['v']) }])"));assert.deepEqual(r.rows,[{total:0.3,average:0.15}]);const half=Engine.run(memory('[[v:1],[v:1.01G]]',"from('rows').aggregate([value:avg { r -> r['v'] }])"));assert.deepEqual(half.rows,[{value:1.01}]);});
test('0 和 false 参数不会使用默认值',()=>{const r=Engine.run(memory('[[id:1]]',"from('rows').map { r -> [value:param('value', 5), enabled:param('enabled', true)] }"),{params:{value:0,enabled:false}});assert.deepEqual(r.rows,[{value:0,enabled:false}]);});
test('闭包 if/return 与安全导航',()=>{const r=Engine.run(memory('[[value:null],[value:[name:\'A\']]]',"from('rows').map { r -> if (r['value'] == null) { return [name:r['value']?.get(decimal(null))] } else { return [name:r['value'].get('name')] } }"));assert.equal(r.error,null);assert.deepEqual(r.rows,[{name:null},{name:'A'}]);});
test('groupBy 空输入与全局空输入不同',()=>{const r=Engine.run(memory('[]',"from('rows').groupBy([key:{ r -> r['key'] }]).aggregate([n:count()])"));assert.deepEqual(r.rows,[]);assert.deepEqual(Engine.run(scripts[5]).rows,[{orderCount:0,totalAmount:0,averageAmount:null}]);});
test('join 空键不匹配、数值键匹配、字符串不强转',()=>{const code=wrap("source('a',[type:'memory',rows:[[id:null],[id:1],[id:'1']]])\nsource('b',[type:'memory',rows:[[id:null,value:'null'],[id:1.0G,value:'yes']]])\ndef result=from('a').join(from('b'),[type:'left',leftKey:{l->l['id']},rightKey:{r->r['id']}]) {l,r->[id:l['id'],value:r==null?null:r['value']]}\nemit(result)");assert.deepEqual(Engine.run(code).rows,[{id:null,value:null},{id:1,value:'yes'},{id:'1',value:null}]);});
test('排序空键始终最后，distinct 保留首行',()=>{const r=Engine.run(memory("[[id:'A',v:null],[id:'B',v:2],[id:'B',v:1],[id:'C',v:3]]","from('rows').distinct { r -> r['id'] }.sorted([direction:'desc']) { r -> r['v'] }"));assert.deepEqual(r.rows.map(x=>x.id),['C','B','A']);});
test('失败定位到真实 join 节点，下游阻断且没有部分输出',()=>{const r=Engine.run(example.replace('"129.90"','"bad"'));assert.equal(r.error.code,'RF-TYPE-001');assert.equal(r.error.nodeId,'enrich');assert.deepEqual(r.rows,[]);assert.equal(r.nodes.find(n=>n.id==='budget').status,'BLOCKED');assert.equal(r.executionOrder.at(-1),'enrich');});
test('同一流被重复消费会拒绝',()=>codeError(wrap("source('s',[type:'memory',rows:[]])\ndef a=from('s')\ndef b=a.map { r -> r }\ndef c=a.filter { r -> true }\nemit(b.union(c))"),'RF-DSL-003'));
test('重复节点注释和伪造结果元数据被拒绝',()=>{codeError(example.replace('// @step products','// @step inventory'),'RF-DEMO-META');codeError(example.replace('"version": "1.0",','"version": "1.0", "expectedRows": [],'),'RF-DEMO-META');});
test('没有样例时显式失败，不能伪装成空输入',()=>{const r=Engine.run(scripts[1]);assert.equal(r.error.code,'RF-DEMO-MOCK');assert.deepEqual(r.rows,[]);assert.equal(r.nodes.find(n=>n.kind==='from').status,'FAILED');});
test('response 路径和类型仍根据脚本校验',()=>{const r=Engine.run(example.replace("rowsPath: 'data.items'","rowsPath: 'data.wrong'"));assert.equal(r.error.code,'RF-SRC-003');assert.equal(r.error.nodeId,'inventory');});
test('filter/map 返回类型错误会停止执行',()=>{assert.equal(Engine.run(memory('[[id:1]]',"from('rows').filter { r -> 'true' }")).error.code,'RF-TYPE-001');assert.equal(Engine.run(memory('[[id:1]]',"from('rows').map { r -> null }")).error.code,'RF-TYPE-001');});
const lookup=wrap("source('s',[type:'memory',rows:[[id:'A'],[id:'Z']]])\nsource('remote',[type:'rpc',mode:'lookup',registryRef:'r',service:'Demo',method:'get',args:[:],recordPath:'data'])\ndef result=from('s').lookup('remote',[request:{r->[id:r['id']]},mode:'left',onError:'null']) {r,u->[id:r['id'],name:u==null?null:u['name']]}\nemit(result)");
test('lookup 样例按动态参数查询并区分未命中',()=>{const r=Engine.run(lookup,{mocks:{remote:{lookup:{key:'id',records:{A:{name:'Alpha'}}}}}});assert.deepEqual(r.rows,[{id:'A',name:'Alpha'},{id:'Z',name:null}]);assert.equal(r.stats.sourceRequests,2);assert.equal(r.stats.lookupMissRows,1);assert.equal(r.stats.lookupErrorFallbackRows,0);});
test('lookup 错误显式降级，额度失败不能降级',()=>{const r=Engine.run(lookup,{mocks:{remote:{error:{code:'RF-SRC-001'}}}});assert.equal(r.stats.lookupErrorFallbackRows,2);assert.equal(r.stats.lookupMissRows,0);const limited=Engine.run(lookup.replace("dslVersion: '1.0'","dslVersion: '1.0', maxLookupCalls: 1"),{mocks:{remote:{error:{code:'RF-SRC-001'}}}});assert.equal(limited.error.code,'RF-LIMIT-001');assert.equal(limited.stats.sourceRequests,1);assert.deepEqual(limited.rows,[]);});
test('lookup 响应结构错误不按源超时降级',()=>{const r=Engine.run(lookup,{mocks:{remote:{response:{data:[]}}}});assert.equal(r.error.code,'RF-SRC-003');assert.equal(r.stats.lookupErrorFallbackRows,0);assert.deepEqual(r.rows,[]);});
test('资源上限与禁用语法明确失败',()=>{codeError('import java.lang.System\n'+memory('[]'),'RF-DSL-001');codeError(memory('[]').replace("emit(result)",'emit(result)\nemit(result)'),'RF-DSL-003');assert.equal(Engine.run(memory('[[id:1],[id:2]]',"from('rows')",', maxRows:1, maxOutputRows:1')).error.code,'RF-LIMIT-001');codeError(' '.repeat(256*1024+1),'RF-DEMO-LIMIT');});
test('业务字段 returned 不会被当成内部 return 信号',()=>{const r=Engine.run(memory("[[returned:true,value:'ok']]","from('rows').map { r -> r }"));assert.equal(r.error,null);assert.deepEqual(r.rows,[{returned:true,value:'ok'}]);});
test('UTF-8 BOM 与多行数字转换仍可读取',()=>assert.deepEqual(Engine.run('\uFEFF'+memory("[[value:' 12.50 ']]","from('rows').map { r -> def amount = decimal(r['value'])\n[amount: amount] }")).rows,[{amount:12.5}]));

const report=path.join(root,'.spec-to-ship/rowflow-import');fs.mkdirSync(report,{recursive:true});fs.writeFileSync(path.join(report,'engine-results.json'),JSON.stringify({status:'PASS',count:cases.length,cases},null,2));console.log('\n'+cases.length+' interpreter checks passed.');
