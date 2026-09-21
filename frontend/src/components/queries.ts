/**
 * React Query keys, hooks and invalidation rules.
 *
 * Components use these instead of touching api.ts directly, so every screen
 * shares one cache entry per resource and one invalidation policy. This file
 * contains no fetch() calls of its own — it only calls api.ts.
 */
import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import * as api from "../api";
import { BATCH_COUNTS_POLL_MS, BATCH_POLL_MS } from "./labels";
import type {
  AttachmentRecord,
  Batch,
  EmailFilters,
  EmailListResult,
  EmailQuery,
  EmailRecord,
  EmailResult,
  ExportFormat,
  ListResponse,
  ReviewCorrectionRequest,
  UploadInput,
  UploadResponse,
} from "../types";

export const queryKeys = {
  health: ["health"] as const,
  emails: (query: EmailQuery = {}) => ["emails", query] as const,
  emailCount: (filters: EmailFilters = {}) => ["emails-count", filters] as const,
  email: (emailId: string) => ["email", emailId] as const,
  attachments: (emailId: string) => ["attachments", emailId] as const,
  batch: (batchId: string) => ["batch", batchId] as const,
};

/** Invalidated whenever a write may have changed any listing or count. */
function invalidateListings(client: ReturnType<typeof useQueryClient>): void {
  void client.invalidateQueries({ queryKey: ["emails"] });
  void client.invalidateQueries({ queryKey: ["emails-count"] });
}

export function useHealth(): UseQueryResult<{ status: string }, api.ApiError> {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: api.getHealth,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
    retry: false,
    staleTime: 15_000,
  });
}

export function useEmails(query: EmailQuery = {}): UseQueryResult<EmailListResult, api.ApiError> {
  return useQuery({
    queryKey: queryKeys.emails(query),
    queryFn: () => api.listEmails(query),
    staleTime: 10_000,
    // Keeps the previous page on screen while the next one loads, so the
    // table does not collapse to skeletons on every page change.
    placeholderData: (previous) => previous,
  });
}

export function useEmailCount(filters: EmailFilters = {}): UseQueryResult<number, api.ApiError> {
  return useQuery({
    queryKey: queryKeys.emailCount(filters),
    queryFn: () => api.countEmails(filters),
    staleTime: 15_000,
  });
}

/** Several counts at once, each with its own loading and error state. */
export function useEmailCounts(filterSets: EmailFilters[]) {
  return useQueries({
    queries: filterSets.map((filters) => ({
      queryKey: queryKeys.emailCount(filters),
      queryFn: () => api.countEmails(filters),
      staleTime: 15_000,
    })),
  });
}

export function useEmail(emailId: string): UseQueryResult<EmailRecord, api.ApiError> {
  return useQuery({
    queryKey: queryKeys.email(emailId),
    queryFn: () => api.getEmail(emailId),
    enabled: Boolean(emailId),
    retry: (failureCount, error) => (error.status === 404 ? false : failureCount < 2),
  });
}

export function useAttachments(
  emailId: string,
): UseQueryResult<ListResponse<AttachmentRecord>, api.ApiError> {
  return useQuery({
    queryKey: queryKeys.attachments(emailId),
    queryFn: () => api.listAttachments(emailId),
    enabled: Boolean(emailId),
  });
}

/** Polls every 3 s while the batch is still processing, then stops. */
export function useBatch(batchId: string): UseQueryResult<Batch, api.ApiError> {
  return useQuery({
    queryKey: queryKeys.batch(batchId),
    queryFn: () => api.getBatch(batchId),
    enabled: Boolean(batchId),
    retry: (failureCount, error) => (error.status === 404 ? false : failureCount < 2),
    refetchInterval: (query) => (query.state.data?.status === "processing" ? BATCH_POLL_MS : false),
  });
}

/**
 * Per-batch counters. GET /api/emails/count runs a full filtered scan
 * server-side, so these refresh far less often than the 3 s progress poll —
 * and stop entirely once the batch is no longer processing.
 */
export function useBatchCounts(batchId: string, filterSets: EmailFilters[], live: boolean) {
  return useQueries({
    queries: filterSets.map((filters) => {
      const withBatch = { ...filters, batch_id: batchId };
      return {
        queryKey: queryKeys.emailCount(withBatch),
        queryFn: () => api.countEmails(withBatch),
        enabled: Boolean(batchId),
        refetchInterval: live ? BATCH_COUNTS_POLL_MS : (false as const),
        staleTime: live ? 0 : 60_000,
      };
    }),
  });
}

/**
 * POST /process and POST /retry return an EmailResult, which carries no
 * processing_status (confirmed in backend/models.py @ 06e4ad4). Their
 * response is therefore never rendered directly — we always invalidate and
 * refetch the record and the lists afterwards, on success AND on failure
 * (a failed run still writes processing_status and last_error server-side).
 */
function useProcessingMutation(
  emailId: string,
  run: (id: string) => Promise<EmailResult>,
): UseMutationResult<EmailResult, api.ApiError, void> {
  const client = useQueryClient();

  return useMutation<EmailResult, api.ApiError, void>({
    mutationFn: () => run(emailId),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: queryKeys.email(emailId) });
      void client.invalidateQueries({ queryKey: queryKeys.attachments(emailId) });
      invalidateListings(client);
    },
  });
}

export function useProcessEmail(emailId: string) {
  return useProcessingMutation(emailId, api.processEmail);
}

export function useRetryEmail(emailId: string) {
  return useProcessingMutation(emailId, api.retryEmail);
}

export function useSubmitReview(
  emailId: string,
): UseMutationResult<EmailRecord, api.ApiError, ReviewCorrectionRequest> {
  const client = useQueryClient();
  return useMutation<EmailRecord, api.ApiError, ReviewCorrectionRequest>({
    mutationFn: (body) => api.submitReview(emailId, body),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: queryKeys.email(emailId) });
      invalidateListings(client);
    },
  });
}

export function useUploadEmail(): UseMutationResult<UploadResponse, api.ApiError, UploadInput> {
  const client = useQueryClient();
  return useMutation<UploadResponse, api.ApiError, UploadInput>({
    mutationFn: (input) => api.uploadEmail(input),
    onSuccess: () => invalidateListings(client),
  });
}

export function useExportEmails(): UseMutationResult<
  api.ExportedFile,
  api.ApiError,
  { format: ExportFormat; filters: EmailFilters }
> {
  return useMutation<api.ExportedFile, api.ApiError, { format: ExportFormat; filters: EmailFilters }>({
    mutationFn: ({ format, filters }) => api.exportEmails(format, filters),
  });
}
