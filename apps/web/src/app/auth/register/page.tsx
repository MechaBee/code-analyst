import RegisterPageClient from './RegisterPageClient';

type RegisterPageProps = {
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

export default async function RegisterPage({ searchParams }: RegisterPageProps) {
  const resolvedSearchParams = searchParams ? await searchParams : {};
  return <RegisterPageClient token={resolveToken(resolvedSearchParams.token)} />;
}
