"use client";
import { useMutation, useQuery, useQueryClient, type UseQueryOptions } from "@tanstack/react-query";
import { api } from "@/services/api";
import type { Catalog, User } from "@/types";

export function useApi<T>(path: string | null, opts?: Partial<UseQueryOptions<T>>) {
  return useQuery<T>({ queryKey: [path], queryFn: () => api.get<T>(path as string), enabled: !!path, ...opts });
}

/** Mutation that invalidates the given query keys (path prefixes) on success. */
export function useAction<TBody = unknown, TRes = unknown>(fn: (b: TBody) => Promise<TRes>, invalidate: string[] = []) {
  const qc = useQueryClient();
  return useMutation<TRes, Error, TBody>({
    mutationFn: fn,
    onSuccess: () =>
      qc.invalidateQueries({
        predicate: (q) => invalidate.some((p) => typeof q.queryKey[0] === "string" && (q.queryKey[0] as string).startsWith(p)),
      }),
  });
}

export const useMe = () => useApi<User>("/auth/me", { retry: false });
export const useCatalog = () => useApi<Catalog>("/meta/catalog", { staleTime: 300_000 });
