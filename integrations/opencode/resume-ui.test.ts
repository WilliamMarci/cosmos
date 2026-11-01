import { expect, test } from "bun:test"
import type { PermissionRequest, SessionInfo } from "@opencode/client"
import { createAppFixture } from "./fixture/app"
import { directory, json } from "./fixture/tui-client"
import { permissionPresentation } from "../src/util/permission"

async function fixture() {
  const session={id:`ses_resume_${crypto.randomUUID()}`,title:"Resume fixture",projectID:"proj_resume",location:{directory},agent:"build",model:{providerID:"fixture",id:"model"},cost:0,tokens:{input:0,output:0,reasoning:0,cache:{read:0,write:0}},time:{created:1,updated:1}} satisfies SessionInfo
  const permission={id:`per_resume_${crypto.randomUUID()}`,sessionID:session.id,action:"cosmos_terminal_request_resume",resources:["resume/fixture"],save:[],metadata:{cosmos_resume:true,pane:"%11",reason:"Continue the user's changed request"}} satisfies PermissionRequest
  const location={directory,project:{id:session.projectID,directory,canonical:directory}}
  const replies: unknown[]=[]
  const setup=await createAppFixture({width:110,height:32,args:{sessionID:session.id},config:{animations:false,tabs:{enabled:false},session:{sidebar:"hide"}},fetch:async(url,request)=>{
    if(url.pathname==="/api/location")return json(location)
    if(url.pathname==="/api/agent")return json({location,data:[{id:"build",mode:"primary",hidden:false,permissions:[]}]})
    if(url.pathname==="/api/model")return json({location,data:[{id:"model",providerID:"fixture",name:"Model",variants:[]}]})
    if(url.pathname==="/api/provider")return json({location,data:[{id:"fixture",name:"Fixture"}]})
    if(url.pathname===`/api/session/${session.id}`)return json({data:session})
    if(url.pathname===`/api/session/${session.id}/message`)return json({data:[],cursor:{}})
    if(url.pathname===`/api/session/${session.id}/inbox`)return json({data:[]})
    if(url.pathname===`/api/session/${session.id}/form`)return json({data:[]})
    if(url.pathname===`/api/session/${session.id}/permission`)return json({data:replies.length ? [] : [permission]})
    if(url.pathname===`/api/session/${session.id}/permission/${permission.id}/reply`){replies.push(await request.json());return new Response(null,{status:204})}
    return undefined
  }})
  return {...setup,replies}
}

test("resume confirmation renders distinct presentation, no Always, defaults to keep paused",async()=>{
  await using setup=await fixture()
  await setup.waitForFrame(frame=>frame.includes("Task resume confirmation")&&frame.includes("Keep paused")&&frame.includes("Resume task"),{maxPasses:120})
  const frame=setup.captureCharFrame()
  expect(frame).toContain("Terminal: %11")
  expect(frame).not.toContain("Allow always")
  expect(setup.renderer.root.findDescendantById("session.permission.action.always")).toBeUndefined()
  expect(permissionPresentation({action:"cosmos_terminal_request_resume",resources:[],metadata:{cosmos_resume:true}}).variant).toBe("resume")
  setup.mockInput.pressEnter()
  await setup.waitFor(()=>setup.replies.length===1)
  expect(setup.replies).toEqual([{decision:"reject"}])
})

test("clicking Resume task sends only the explicit once decision",async()=>{
  await using setup=await fixture()
  await setup.waitForFrame(frame=>frame.includes("Task resume confirmation"),{maxPasses:120})
  const resume=setup.renderer.root.findDescendantById("session.permission.action.once")!
  expect(resume).toBeDefined()
  await setup.mockMouse.click(resume.x+1,resume.y)
  await setup.waitFor(()=>setup.replies.length===1)
  expect(setup.replies).toEqual([{decision:"once"}])
})
