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

import "./styles.css";

type PageDefinition = {
  path: string;
  title: string;
  eyebrow: string;
  description: string;
  icon: typeof Goal;
  metric: string;
  metricLabel: string;
  rows: Array<[string, string, string]>;
};

const pages: PageDefinition[] = [
  { path: "/goals", title: "目标中心", eyebrow: "GOAL CONTROL", description: "跨会话持续推进可验证业务结果。", icon: Goal, metric: "24", metricLabel: "活跃目标", rows: [["供应风险缓解", "运行中", "8 分钟前"], ["季度续约分析", "等待证据", "21 分钟前"], ["设备恢复", "等待审批", "34 分钟前"]] },
  { path: "/runs", title: "运行时间线", eyebrow: "DURABLE RUNTIME", description: "追踪 Task、Action、暂停、恢复和副作用证据。", icon: Activity, metric: "97.8%", metricLabel: "恢复成功率", rows: [["RUN-8F31", "执行中", "Temporal"], ["RUN-8EFA", "等待审批", "L2 写入"], ["RUN-8DC2", "已验证", "Outcome"]] },
  { path: "/approvals", title: "审批队列", eyebrow: "HUMAN OVERSIGHT", description: "审阅真实参数、影响范围和回滚方式。", icon: FileCheck2, metric: "6", metricLabel: "待处理", rows: [["创建外部记录", "L2 可逆写", "15 分钟后过期"], ["发送客户通知", "L3 外部承诺", "27 分钟后过期"], ["晋升候选版本", "发布门禁", "2 小时后过期"]] },
  { path: "/agents", title: "Agent 资产", eyebrow: "VERSIONED INTELLIGENCE", description: "管理 Agent 定义、能力边界和 Stable 版本。", icon: Bot, metric: "12", metricLabel: "Stable Agent", rows: [["research-planner", "v7 Stable", "评估 0.94"], ["operations-agent", "v4 Stable", "评估 0.91"], ["review-agent", "v9 Candidate", "评估中"]] },
  { path: "/skills", title: "Skill 目录", eyebrow: "REUSABLE CAPABILITIES", description: "版本化成功经验、输入输出和评估标准。", icon: Sparkles, metric: "38", metricLabel: "已发布 Skill", rows: [["evidence-synthesis", "v3.2.0", "Stable"], ["risk-review", "v2.1.0", "Stable"], ["goal-clarification", "v1.4.0", "Candidate"]] },
  { path: "/tools", title: "Tool Gateway", eyebrow: "SIDE-EFFECT BOUNDARY", description: "统一查看风险、幂等、审批、验证和 Kill Switch。", icon: Wrench, metric: "4", metricLabel: "受控写工具", rows: [["enterprise.search", "L1 只读", "可用"], ["record.create", "L2 可逆写", "需审批"], ["notification.send", "L3 高影响", "已限流"]] },
  { path: "/packs", title: "能力包", eyebrow: "CAPABILITY PACKS", description: "安装行业 Goal Type、Agent、Skill、Tool 与评估套件。", icon: PackageOpen, metric: "1", metricLabel: "已启用能力包", rows: [["field-service", "v0.1.0", "1 Goal Type"], ["核心契约", "v1alpha1", "兼容"]] },
  { path: "/policies", title: "策略与身份", eyebrow: "GOVERNANCE", description: "检查 OIDC 委托链、OPA 决策和最小权限。", icon: ShieldCheck, metric: "100%", metricLabel: "Action 执行时复核", rows: [["production-write", "OPA v12", "启用"], ["cross-tenant-deny", "平台不变量", "强制"], ["candidate-promotion", "人工审批", "启用"]] },
  { path: "/budgets", title: "预算与成本", eyebrow: "AI FINOPS", description: "按成功 Goal 衡量模型、工具、评估和人工成本。", icon: CircleDollarSign, metric: "¥18.40", metricLabel: "单位成功 Goal", rows: [["模型调用", "42%", "预算内"], ["工具与沙箱", "23%", "预算内"], ["人工审批", "35%", "需优化"]] },
  { path: "/evaluations", title: "评估实验室", eyebrow: "INDEPENDENT EVALUATION", description: "固定 Case、Harness、环境和 Grader 比较版本。", icon: GitCompareArrows, metric: "142", metricLabel: "本周 Trial", rows: [["field-service-recovery", "10 Cases", "通过 9/10"], ["prompt-injection", "24 Cases", "通过 24/24"], ["recovery-suite", "18 Cases", "通过 17/18"]] },
  { path: "/improvements", title: "进化与发布", eyebrow: "GOVERNED EVOLUTION", description: "从运行证据到 Candidate、审批、Stable 与回滚。", icon: BrainCircuit, metric: "3", metricLabel: "候选改进", rows: [["agent-instruction v8", "等待审批", "+6.2%"], ["model-route v5", "评估中", "成本 -11%"], ["skill v3.3", "已拒绝", "风险回归"]] },
  { path: "/audit", title: "审计与证据", eyebrow: "EXPLAINABILITY", description: "重建谁基于什么事实、策略和版本采取了行动。", icon: ScrollText, metric: "0", metricLabel: "不可解释 Action", rows: [["goal.created", "actor: 8A2F", "已关联"], ["action.approved", "policy: v12", "已关联"], ["outcome.verified", "evidence: 4 refs", "已关联"]] },
];

const navGroups = [
  { label: "运行", paths: ["/", "/goals", "/runs", "/approvals"] },
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
            const page = path === "/" ? undefined : pages.find((item) => item.path === path);
            const Icon = page?.icon ?? Gauge;
            return <Link key={path} to={path} activeProps={{ className: "active" }} onClick={() => setOpen(false)}><Icon size={17}/><span>{page?.title ?? "总览"}</span></Link>;
          })}</div>)}
        </nav>
        <div className="tenant-card"><div className="tenant-icon"><Boxes size={18}/></div><div><span>示例租户</span><strong>Acme / Demo</strong></div><ChevronRight size={16}/></div>
      </aside>
      <main>
        <header className="topbar"><button className="menu" onClick={() => setOpen(true)} aria-label="打开菜单"><Menu /></button><div className="environment"><span className="pulse"/>原型界面可访问</div><div className="identity"><KeyRound size={16}/><span>demo-operator@acme</span><b>演示身份</b></div></header>
        <div className="prototype-banner" role="status" data-testid="prototype-banner"><strong>Prototype / Demo</strong><span>当前页面使用静态样例数据，不代表真实运行状态、生产能力或审计证据。</span></div>
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

function ControlPage({ page }: { page: PageDefinition }) {
  const Icon = page.icon;
  return <div className="page"><PageHeader eyebrow={`${page.eyebrow} · STATIC SAMPLE`} title={page.title} description={`静态演示：${page.description}`} /><section className="section-grid"><div className="metric-card"><div className="metric-icon"><Icon/></div><span>{page.metricLabel}</span><strong>{page.metric}</strong><p>样例指标，尚未连接真实 API</p></div><div className="panel table-panel"><PanelTitle title="最近活动（样例）"/><div className="table-head"><span>对象</span><span>状态 / 版本</span><span>更新时间 / 说明</span></div>{page.rows.map((row) => <div className="table-row" key={row[0]}><strong>{row[0]}</strong><span><i />{row[1]}</span><small>{row[2]}</small></div>)}</div></section></div>;
}

function PageHeader({eyebrow,title,description}:{eyebrow:string;title:string;description:string}) { return <div className="page-header"><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>; }
function Stat({label,value,delta}:{label:string;value:string;delta:string}) { return <div className="stat-card"><span>{label}</span><strong>{value}</strong><small>{delta}</small></div>; }
function PanelTitle({title,action}:{title:string;action?:string}) { return <div className="panel-title"><h3>{title}</h3>{action && <button>{action}<ChevronRight size={14}/></button>}</div>; }
function FlowStep({label,value,last}:{label:string;value:string;last?:boolean}) { return <><div className="flow-step"><strong>{value}</strong><span>{label}</span></div>{!last&&<ChevronRight className="flow-arrow"/>}</>; }
function Signal({icon:Icon,label,value,tone}:{icon:typeof Goal;label:string;value:string;tone:string}) { return <div className="signal"><div className={`signal-icon ${tone}`}><Icon size={17}/></div><span>{label}</span><strong>{value}</strong></div>; }

const rootRoute = createRootRoute({ component: Shell });
const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: Overview });
const childRoutes = pages.map((page) => createRoute({ getParentRoute: () => rootRoute, path: page.path, component: () => <ControlPage page={page}/> }));
const routeTree = rootRoute.addChildren([indexRoute, ...childRoutes]);
const router = createRouter({ routeTree });
declare module "@tanstack/react-router" { interface Register { router: typeof router; } }
const queryClient = new QueryClient();

createRoot(document.getElementById("root")!).render(<QueryClientProvider client={queryClient}><RouterProvider router={router}/></QueryClientProvider>);
