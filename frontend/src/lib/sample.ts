import type { FormValues } from "@/lib/report-form";

/**
 * A tiny repository with a planted bug and a matching report, so the form can be tried without
 * bringing anything. The archive is built from fixtures/repos/exception_bug by
 * scripts/make-sample.py, and a test checks that the two stay identical and that the report
 * describes the bug that is really in the code.
 */
export const SAMPLE = {
  projectName: "Sample project",
  archiveUrl: "/samples/accounts-demo.zip",
  archiveName: "accounts-demo.zip",
  values: {
    title: "register crashes without username",
    description:
      "Registering a user with an email but no username fails with a raw KeyError instead of a validation error.",
    expected_behavior: "register() raises ValueError('username is required') when the username is missing.",
    actual_behavior: "KeyError: 'username'",
    reproduction_steps: "Call register({'email': 'a@b.c'}).",
    stack_trace:
      'Traceback (most recent call last):\n  File "accounts/registration.py", line 9, in register\n    username = data["username"]\nKeyError: \'username\'',
    environment: "Python 3.12",
  } satisfies FormValues,
};

/** Fetch the bundled archive as a File, ready for the normal upload path. */
export async function loadSampleArchive(fetcher: typeof fetch = fetch): Promise<File> {
  let res: Response;
  try {
    res = await fetcher(SAMPLE.archiveUrl);
  } catch {
    throw new Error("Could not load the sample archive.");
  }
  if (!res.ok) throw new Error(`Could not load the sample archive (HTTP ${res.status}).`);
  return new File([await res.arrayBuffer()], SAMPLE.archiveName, { type: "application/zip" });
}
