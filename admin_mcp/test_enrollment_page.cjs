const {test} = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const source = fs.readFileSync(__dirname+"/enrollment_page.js","utf8").replace(/^import .*;\r?\n/,"");
function setup(fail=false) {
    const fields = {enrollment:{addEventListener(_,fn){this.submit=fn}},status:{},register:{disabled:false},token:{value:"temporary-token"},operator:{value:"operator"}};
    const calls=[];
    const context=vm.createContext({
        document:{getElementById:id=>fields[id]},
        createOperatorPasskey:async()=>({id:"credential"}),
        fetch:async(url,options)=>{
            calls.push({url,options,tokenField:fields.token.value});
            return {ok:!fail,json:async()=>url.endsWith("/options")?{challenge:"challenge"}:{status:"registered"}};
        }
    });
    vm.runInContext(source,context);
    return {fields,calls,context,submit:()=>fields.enrollment.submit({preventDefault(){}})};
}
test("same-origin credentials and restricted request settings",async()=>{
    const s=setup(); await s.submit();
    assert.equal(s.calls.length,2);
    assert.deepEqual(s.calls.map(c=>c.url),["/admin/enroll/options","/admin/enroll/complete"]);
    for(const c of s.calls){
        assert.equal(c.options.credentials,"same-origin");
        assert.equal(c.options.redirect,"error");
        assert.equal(c.options.cache,"no-store");
        assert.equal(c.options.method,"POST");
        assert.equal(c.options.headers.Authorization,"Bearer temporary-token");
        assert.equal(c.tokenField,"");
        assert.ok(!c.options.body.includes("temporary-token"));
    }
    assert.equal(s.fields.enrollment.hidden,true);
});
test("invalid action rejected before network request",async()=>{
    const s=setup();
    await assert.rejects(vm.runInContext('post("../other", {}, "token")',s.context),/Invalid enrollment action/);
    assert.equal(s.calls.length,0);
});
test("failed options request clears token and restores button",async()=>{
    const s=setup(true); await s.submit();
    assert.equal(s.calls.length,1);
    assert.equal(s.fields.token.value,"");
    assert.equal(s.fields.register.disabled,false);
    assert.match(s.fields.status.textContent,/failed/);
});
test("duplicate submissions blocked while registration pending",async()=>{
    const s=setup(); await Promise.all([s.submit(),s.submit()]);
    assert.equal(s.calls.length,2);
});
