import SignInPageClient from './SignInPageClient';

type SignInPageProps = {
  searchParams?: Promise<{
    token?: string | string[] | undefined;
  }>;
};

function resolveToken(token: string | string[] | undefined): string {
  if (Array.isArray(token)) {
    return token[0] || '';
  }
  return token || '';
}

export default async function SignInPage({ searchParams }: SignInPageProps) {
  const resolvedSearchParams = searchParams ? await searchParams : {};
  return <SignInPageClient token={resolveToken(resolvedSearchParams.token)} />;
}
