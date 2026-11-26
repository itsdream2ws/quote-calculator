/* Which Supabase project the app saves to.
 * The publishable key is meant to be public: it only lets the app ask Supabase to log in.
 * Row level security in the database (supabase/schema.sql) blocks every read and write
 * until someone has logged in with an account the owner created. */
window.QC_CONFIG = {
  supabaseUrl: 'https://lhbxixvazowgiquiexzt.supabase.co',
  supabaseKey: 'sb_publishable_7b556YBCnP2oRi7NDO8cGg_WNlPYX_t',
  // People log in with an agent code (e.g. AG01) and a password. Behind the scenes the
  // code is the first part of their login email: AG01 -> ag01@agents.local. Add agents in
  // Supabase with emails ending in this domain (see README).
  agentEmailDomain: 'agents.local'
};
