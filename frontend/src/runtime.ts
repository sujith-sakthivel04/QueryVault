export type Runtime={mode:'local'|'public_demo'|'public_interactive';preview?:{template:string;sql:string};interactive_ai?:boolean};
export const isPublicDemo=(runtime?:Runtime)=>runtime?.mode==='public_demo';
export const isPublicMode=(runtime?:Runtime)=>runtime?.mode==='public_demo'||runtime?.mode==='public_interactive';
export const workspaceTab=(path:string)=>/^\/seller(?:\/|$)/.test(path)?'seller':'buyer';
export function previewBody(runtime:Runtime|undefined,sql:string){
 if(isPublicDemo(runtime))return {template:runtime!.preview?.template||'port_delays'};
 return {sql};
}
