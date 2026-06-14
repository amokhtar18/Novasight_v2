/**
 * UsersPanel — tenant-scoped user management (Admin page).
 *
 * Lists the tenant's users and lets a superuser create, edit (name, roles, active
 * state, password reset), and delete them. The platform-admin role toggle is only
 * offered to a platform admin; the backend enforces the same rule regardless.
 */

import { useState } from "react";
import { Plus, Trash2, UserCog, Users as UsersIcon } from "lucide-react";
import { toast } from "sonner";

import {
  useCreateUser,
  useDeleteUser,
  useUpdateUser,
  useUsers,
} from "@/api/hooks";
import { useIdentity } from "@/lib/identity";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Dialog,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { UserRead } from "@/types/api";

const SUPERUSER_ROLE = "superuser";
const PLATFORM_ADMIN_ROLE = "platform_admin";
const VIEWER_ROLE = "viewer";

function errMsg(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

export function UsersPanel() {
  const { isPlatformAdmin } = useIdentity();
  const { data: users, isLoading, isError } = useUsers();
  const createUser = useCreateUser();
  const updateUser = useUpdateUser();
  const deleteUser = useDeleteUser();

  const [createOpen, setCreateOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [superuser, setSuperuser] = useState(false);
  const [platformAdmin, setPlatformAdmin] = useState(false);
  const [viewer, setViewer] = useState(false);

  const [deleteTarget, setDeleteTarget] = useState<UserRead | null>(null);

  function resetCreate() {
    setEmail("");
    setName("");
    setPassword("");
    setSuperuser(false);
    setPlatformAdmin(false);
    setViewer(false);
  }

  function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const roles = [
      ...(superuser ? [SUPERUSER_ROLE] : []),
      ...(platformAdmin ? [PLATFORM_ADMIN_ROLE] : []),
      ...(viewer ? [VIEWER_ROLE] : []),
    ];
    createUser.mutate(
      { email: email.trim(), name: name.trim() || null, password, roles },
      {
        onSuccess: () => {
          toast.success(`User “${email.trim()}” created`);
          resetCreate();
          setCreateOpen(false);
        },
        onError: (err) => toast.error(errMsg(err, "Could not create user")),
      }
    );
  }

  function toggleRole(user: UserRead, role: string, on: boolean) {
    const roles = on
      ? Array.from(new Set([...user.roles, role]))
      : user.roles.filter((r) => r !== role);
    updateUser.mutate(
      { id: user.id, patch: { roles } },
      { onError: (err) => toast.error(errMsg(err, "Could not update roles")) }
    );
  }

  function toggleActive(user: UserRead, isActive: boolean) {
    updateUser.mutate(
      { id: user.id, patch: { is_active: isActive } },
      { onError: (err) => toast.error(errMsg(err, "Could not update user")) }
    );
  }

  function handleDelete() {
    if (!deleteTarget) return;
    deleteUser.mutate(deleteTarget.id, {
      onSuccess: () => {
        toast.success(`User “${deleteTarget.email}” deleted`);
        setDeleteTarget(null);
      },
      onError: (err) => {
        toast.error(errMsg(err, "Could not delete user"));
        setDeleteTarget(null);
      },
    });
  }

  return (
    <Card className="bg-card/70">
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <UsersIcon className="h-4 w-4 text-primary" aria-hidden />
            Users
          </CardTitle>
          <CardDescription>Manage who can access this workspace.</CardDescription>
        </div>
        <Button size="sm" onClick={() => setCreateOpen(true)}>
          <Plus className="h-4 w-4" aria-hidden />
          New user
        </Button>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : isError ? (
          <Alert variant="destructive">
            <AlertTitle>Couldn't load users</AlertTitle>
            <AlertDescription>You may not have permission to manage users.</AlertDescription>
          </Alert>
        ) : (
          <div className="overflow-hidden rounded-lg border">
            <table className="w-full text-sm">
              <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">User</th>
                  <th className="px-3 py-2 font-medium">Superuser</th>
                  <th className="px-3 py-2 font-medium">Viewer</th>
                  {isPlatformAdmin && <th className="px-3 py-2 font-medium">Platform admin</th>}
                  <th className="px-3 py-2 font-medium">Active</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {(users ?? []).map((u) => (
                  <tr key={u.id} className="border-t border-border/60">
                    <td className="px-3 py-2">
                      <div className="font-medium">{u.name || u.email}</div>
                      <div className="text-xs text-muted-foreground">{u.email}</div>
                    </td>
                    <td className="px-3 py-2">
                      <Switch
                        checked={u.roles.includes(SUPERUSER_ROLE)}
                        onCheckedChange={(on) => toggleRole(u, SUPERUSER_ROLE, on)}
                        aria-label="Toggle superuser"
                      />
                    </td>
                    <td className="px-3 py-2">
                      <Switch
                        checked={u.roles.includes(VIEWER_ROLE)}
                        onCheckedChange={(on) => toggleRole(u, VIEWER_ROLE, on)}
                        aria-label="Toggle viewer (read-only)"
                      />
                    </td>
                    {isPlatformAdmin && (
                      <td className="px-3 py-2">
                        <Switch
                          checked={u.roles.includes(PLATFORM_ADMIN_ROLE)}
                          onCheckedChange={(on) => toggleRole(u, PLATFORM_ADMIN_ROLE, on)}
                          aria-label="Toggle platform admin"
                        />
                      </td>
                    )}
                    <td className="px-3 py-2">
                      {u.is_active ? (
                        <Switch
                          checked
                          onCheckedChange={() => toggleActive(u, false)}
                          aria-label="Deactivate user"
                        />
                      ) : (
                        <Badge variant="warning">inactive</Badge>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Delete ${u.email}`}
                        onClick={() => setDeleteTarget(u)}
                      >
                        <Trash2 className="h-4 w-4 text-destructive" aria-hidden />
                      </Button>
                    </td>
                  </tr>
                ))}
                {(users ?? []).length === 0 && (
                  <tr>
                    <td
                      colSpan={isPlatformAdmin ? 6 : 5}
                      className="px-3 py-6 text-center text-muted-foreground"
                    >
                      No users yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>

      {/* Create user dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen} title="New user">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <UserCog className="h-5 w-5 text-primary" aria-hidden />
            New user
          </DialogTitle>
          <DialogDescription>Create a user in this workspace.</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="u-email">Email</Label>
            <Input
              id="u-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="u-name">Name</Label>
            <Input id="u-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="u-password">Password</Label>
            <Input
              id="u-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={8}
              required
            />
          </div>
          <div className="flex items-center justify-between">
            <Label htmlFor="u-superuser">Superuser (manage data + schedules)</Label>
            <Switch id="u-superuser" checked={superuser} onCheckedChange={setSuperuser} />
          </div>
          <div className="flex items-center justify-between">
            <Label htmlFor="u-viewer">Viewer (read-only)</Label>
            <Switch id="u-viewer" checked={viewer} onCheckedChange={setViewer} />
          </div>
          {isPlatformAdmin && (
            <div className="flex items-center justify-between">
              <Label htmlFor="u-admin">Platform admin (manage tenants)</Label>
              <Switch id="u-admin" checked={platformAdmin} onCheckedChange={setPlatformAdmin} />
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={createUser.isPending}>
              {createUser.isPending ? "Creating…" : "Create user"}
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Delete confirm */}
      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
        title="Delete user"
      >
        <DialogHeader>
          <DialogTitle>Delete “{deleteTarget?.email}”?</DialogTitle>
          <DialogDescription>This permanently removes the user.</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setDeleteTarget(null)}>
            Cancel
          </Button>
          <Button variant="destructive" disabled={deleteUser.isPending} onClick={handleDelete}>
            {deleteUser.isPending ? "Deleting…" : "Delete"}
          </Button>
        </DialogFooter>
      </Dialog>
    </Card>
  );
}
