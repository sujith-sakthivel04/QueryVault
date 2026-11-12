import {expect,test} from 'vitest';
import {isPublicDemo,previewBody,workspaceTab} from './runtime';
test('restricted mode never sends editor text as executable SQL',()=>{
 const runtime={mode:'public_demo' as const,preview:{template:'port_delays',sql:'fixed example'}};
 expect(isPublicDemo(runtime)).toBe(true);
 expect(previewBody(runtime,'SELECT private_data')).toEqual({template:'port_delays'});
});
test('local workbench preserves its SQL workflow',()=>{
 expect(isPublicDemo({mode:'local'})).toBe(false);
 expect(previewBody({mode:'local'},'SELECT COUNT(*) FROM shipments')).toEqual({sql:'SELECT COUNT(*) FROM shipments'});
});
test('seller deep links restore seller workspace while other pages use buyer',()=>{
 expect(workspaceTab('/seller/ledger')).toBe('seller');
 expect(workspaceTab('/seller')).toBe('seller');
 expect(workspaceTab('/buyer/research')).toBe('buyer');
 expect(workspaceTab('/')).toBe('buyer');
 expect(workspaceTab('/seller-other')).toBe('buyer');
});
