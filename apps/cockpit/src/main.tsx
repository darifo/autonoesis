import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Link,
  Outlet,
  RouterProvider,
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router";
import {
  Activity,
  Bot,
  Boxes,
  BrainCircuit,
  CheckCircle2,
  ChevronRight,
  CircleDollarSign,
  FileCheck2,
  Fingerprint,
  Gauge,
  GitCompareArrows,
  Goal,
  History,
  KeyRound,
  Menu,
  PackageOpen,
  ScrollText,
  ShieldCheck,
  Sparkles,
  Wrench,
  X,
} from "lucide-react";
import { useState } from "react";
import { createRoot } from "react-dom/client";

import { OperationsPage } from "./operations";
import { ResourcePage } from "./pages";
import { PROTOTYPE_DISCLOSURE, PROTOTYPE_LABEL } from "./maturity";
import "./styles.css";

// Live pages fetch real platform state; static pages remain for surfaces
// without read APIs yet and are explicitly labelled as samples.
const livePages: Array<{
  path: string;
  title: string;
  eyebrow: string;
  description: string;
  endpoint: string;
  columns: string[];
}> = [
  { path: "/goals", title: "目标中心", eyebrow: "GOAL CONTROL", description: "跨会话持续推进可验证业务结果（真实数据）。", endpoint: "/v1/goals", columns: ["goal_id", "goal_type", "status", "owner_id"] },
  { path: "/runs", title: "运行时间线", eyebrow: "DURABLE RUNTIME", description: "追踪 Task、Action、暂停、恢复和副作用证据（真实数据）。", endpoint: "/v1/runs", columns: ["run_id", "goal_id", "status", "agent_version_id"] },
  { path: "/approvals", title: "审批队列", eyebrow: "HUMAN OVERSIGHT", description: "审阅真实参数、影响范围和回滚方式（真实数据）。", endpoint: "/v1/approvals", columns: ["approval_id", "status", "required_role", "expires_at"] },
  { path: "/agents", title: "Agent 资产", eyebrow: "VERSIONED INTELLIGENCE", description: "管理 Agent 定义、能力边界和 Stable 版本（真实数据）。", endpoint: "/v1/agents", columns: ["name", "version", "stage", "model_route"] },
  { path: "/skills", title: "Skill 目录", eyebrow: "REUSABLE CAPABILITIES", description: "版本化成功经验、输入输出和评估标准（真实数据）。", endpoint: "/v1/skills", columns: ["skill_id", "version", "stage"] },
  { path: "/tools", title: "Tool Gateway", eyebrow: "SIDE-EFFECT BOUNDARY", description: "统一查看风险、幂等、审批、验证和 Kill Switch（真实数据）。", endpoint: "/v1/tools", columns: ["tool_id", "version", "risk_level"] },
  { path: "/packs", title: "能力包", eyebrow: "CAPABILITY PACKS", description: "已安装的签名能力包与版本（真实数据）。", endpoint: "/v1/capability-packs", columns: ["pack_id", "version", "goal_types"] },
  { path: "/policies", title: "策略与身份", eyebrow: "GOVERNANCE", description: "当前生效的策略资产（真实数据）。", endpoint: "/v1/policies", columns: ["policy_id", "version"] },
  { path: "/budgets", title: "预算与成本", eyebrow: "AI FINOPS", description: "SLO 错误预算与真实事件计算的指标（真实数据）。", endpoint: "/v1/slos", columns: ["sli", "total_budget", "consumed", "remaining", "exhausted"] },
  { path: "/evaluations", title: "评估实验室", eyebrow: "INDEPENDENT EVALUATION", description: "持久化评估套件目录（真实数据）。", endpoint: "/v1/evaluation-suites", columns: ["suite_id", "version", "cases"] },
  { path: "/improvements", title: "进化与发布", eyebrow: "GOVERNED EVOLUTION", description: "Release 与 Candidate 发布状态（真实数据）。", endpoint: "/v1/releases", columns: ["release_id", "stable_version_id", "candidate_id"] },
  { path: "/audit", title: "审计与证据", eyebrow: "EXPLAINABILITY", description: "哈希链审计事件与 audit_ref（真实数据）。", endpoint: "/v1/audit-events", columns: ["sequence", "event_type", "object_id", "event_digest"] },
];


const navGroups = [
  { label: "运行", paths: ["/", "/goals", "/runs", "/approvals"] },
  { label: "运营", paths: ["/operations"] },
  { label: "能力", paths: ["/agents", "/skills", "/tools", "/packs"] },
  { label: "控制", paths: ["/policies", "/budgets", "/evaluations", "/improvements", "/audit"] },
];

function Shell() {
  const [open, setOpen] = useState(false);
  return (
    <div className="app-shell">
      <aside className={open ? "sidebar open" : "sidebar"}>
        <div className="brand"><div className="brand-mark"><Fingerprint size={21} /></div><div><strong>Autonoesis</strong><span>AI Agent Operating System</span></div></div>
        <button className="close-nav" onClick={() => setOpen(false)} aria-label="关闭菜单"><X /></button>
        <nav>
          {navGroups.map((group) => <div className="nav-group" key={group.label}><p>{group.label}</p>{group.paths.map((path) => {
            const page = path === "/" ? undefined : livePages.find((item) => item.path === path);
            const isOperations = path === "/operations";
            const Icon = isOperations ? Wrench : (page ? Activity : Gauge);
            const title = isOperations ? "运营操作中心" : (page?.title ?? "总览");
            return <Link key={path} to={path} activeProps={{ className: "active" }} onClick={() => setOpen(false)}><Icon size={17}/><span>{title}</span></Link>;
          })}</div>)}
        </nav>
        <div className="tenant-card"><div className="tenant-icon"><Boxes size={18}/></div><div><span>示例租户</span><strong>Acme / Demo</strong></div><ChevronRight size={16}/></div>
      </aside>
      <main>
        <header className="topbar"><button className="menu" onClick={() => setOpen(true)} aria-label="打开菜单"><Menu /></button><div className="environment"><span className="pulse"/>原型界面可访问</div><div className="identity"><KeyRound size={16}/><span>demo-operator@acme</span><b>演示身份</b></div></header>
        <div className="prototype-banner" role="status" data-testid="prototype-banner"><strong>{PROTOTYPE_LABEL}</strong><span>{PROTOTYPE_DISCLOSURE}</span></div>
        <Outlet />
      </main>
      {open && <button className="scrim" aria-label="关闭菜单" onClick={() => setOpen(false)} />}
    </div>
  );
}

function Overview() {
  return <div className="page"><PageHeader eyebrow="OPERATING PICTURE · STATIC SAMPLE" title="智能运行总览" description="静态演示：展示目标、执行、治理和进化四个维度的目标界面形态。" />
    <section className="hero-grid"><div className="hero-card"><div><span className="eyebrow">单位成功目标</span><h2>¥18.40</h2><p>较上周下降 8.2%</p></div><div className="orb"><BrainCircuit size={34}/></div></div><Stat label="活跃 Goal" value="24" delta="+4"/><Stat label="等待审批" value="6" delta="2 个高风险"/><Stat label="候选版本" value="3" delta="1 个可晋升"/></section>
    <section className="dashboard-grid"><div className="panel span-two"><PanelTitle title="运行态势" action="查看全部运行"/><div className="flow"><FlowStep label="目标已接收" value="128"/><FlowStep label="正在执行" value="24"/><FlowStep label="等待证据" value="7"/><FlowStep label="结果已验证" value="97" last/></div><div className="timeline-bars">{[48, 65, 54, 78, 62, 86, 74, 91, 84, 96, 88, 93].map((height, index)=><span key={index} style={{height: `${height}%`}}/>)}</div></div><div className="panel"><PanelTitle title="治理信号"/><Signal icon={ShieldCheck} label="策略拒绝" value="12" tone="good"/><Signal icon={FileCheck2} label="人工审批" value="19" tone="neutral"/><Signal icon={History} label="恢复执行" value="7" tone="neutral"/><Signal icon={CheckCircle2} label="重复副作用" value="0" tone="good"/></div></section>
  </div>;
}


function PageHeader({eyebrow,title,description}:{eyebrow:string;title:string;description:string}) { return <div className="page-header"><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>; }
function Stat({label,value,delta}:{label:string;value:string;delta:string}) { return <div className="stat-card"><span>{label}</span><strong>{value}</strong><small>{delta}</small></div>; }
function PanelTitle({title,action}:{title:string;action?:string}) { return <div className="panel-title"><h3>{title}</h3>{action && <button>{action}<ChevronRight size={14}/></button>}</div>; }
function FlowStep({label,value,last}:{label:string;value:string;last?:boolean}) { return <><div className="flow-step"><strong>{value}</strong><span>{label}</span></div>{!last&&<ChevronRight className="flow-arrow"/>}</>; }
function Signal({icon:Icon,label,value,tone}:{icon:typeof Goal;label:string;value:string;tone:string}) { return <div className="signal"><div className={`signal-icon ${tone}`}><Icon size={17}/></div><span>{label}</span><strong>{value}</strong></div>; }

const rootRoute = createRootRoute({ component: Shell });
const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: Overview });
const liveRoutes = livePages.map((page) =>
  createRoute({
    getParentRoute: () => rootRoute,
    path: page.path,
    component: () => (
      <ResourcePage
        title={page.title}
        eyebrow={page.eyebrow}
        description={page.description}
        path={page.endpoint}
        columns={page.columns}
      />
    ),
  }),
);
const operationsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/operations", component: OperationsPage });
const childRoutes = [...liveRoutes, operationsRoute];
const routeTree = rootRoute.addChildren([indexRoute, ...childRoutes]);
const router = createRouter({ routeTree });
declare module "@tanstack/react-router" { interface Register { router: typeof router; } }
const queryClient = new QueryClient();

createRoot(document.getElementById("root")!).render(<QueryClientProvider client={queryClient}><RouterProvider router={router}/></QueryClientProvider>);
