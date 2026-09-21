import { Compass } from "lucide-react";
import { useEffect } from "react";
import { Link } from "react-router-dom";

import { PageHeader } from "./AppShell";
import { setDocumentTitle } from "./format";
import { Button, EmptyState, Panel } from "./ui";

export function NotFoundPage() {
  useEffect(() => {
    setDocumentTitle("Page not found");
  }, []);

  return (
    <>
      <PageHeader title="Page not found" description="That address does not match any screen in SDOC." />
      <Panel>
        <EmptyState
          icon={Compass}
          title="Nothing here"
          message="Check the link, or go back to the dashboard to start again."
          action={
            <Link to="/">
              <Button variant="primary">Go to dashboard</Button>
            </Link>
          }
        />
      </Panel>
    </>
  );
}
