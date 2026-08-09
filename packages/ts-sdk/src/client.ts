export type ClientIdentity = {
  tenantId: string;
  actorId: string;
  principalId: string;
  roles: string[];
};

export type GoalView = {
  goal_id: string;
  goal_type: string;
  statement: string;
  desired_outcome: string;
  status: string;
  version: number;
};

export class AutonoesisClient {
  constructor(private baseUrl: string, private identity: ClientIdentity) {}

  private headers(write = false): HeadersInit {
    return {
      "Content-Type": "application/json",
      "X-Tenant-ID": this.identity.tenantId,
      "X-Actor-ID": this.identity.actorId,
      "X-Principal-ID": this.identity.principalId,
      "X-Roles": this.identity.roles.join(","),
      ...(write ? { "Idempotency-Key": crypto.randomUUID() } : {}),
    };
  }

  async listGoals(): Promise<GoalView[]> {
    const response = await fetch(`${this.baseUrl}/v1/goals`, { headers: this.headers() });
    if (!response.ok) throw new Error(`Autonoesis API error: ${response.status}`);
    return response.json() as Promise<GoalView[]>;
  }

  async createGoal(payload: unknown): Promise<GoalView> {
    const response = await fetch(`${this.baseUrl}/v1/goals`, {
      method: "POST",
      headers: this.headers(true),
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(`Autonoesis API error: ${response.status}`);
    return response.json() as Promise<GoalView>;
  }
}
