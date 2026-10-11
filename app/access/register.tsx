import React, { useState } from 'react';
import { Text } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useAccessT } from '../../constants/accessI18n';
import { AuthButton, AuthScreen, Notice, isValidEmail, isValidName, normalizeIndianMobile } from '../../components/auth/AuthUi';
import { accessStyles, Choice, ErrorText, Field } from '../../components/access/AccessUi';
import { routeAfterLogin } from '../../components/access/routeAfterLogin';
import { AccessApi } from '../../services/accessApi';
import { parseDob } from '../../components/access/dob';

/**
 * Passenger sign-up: "Who are you?" then one follow-up question.
 *   Male   → "Do you have a valid Bus Pass?"  (Yes → college verification of the pass, No → regular paid tickets)
 *   Female → "Do you have an Aadhaar card?"   (Yes → DigiLocker + face verification, No → regular paid tickets)
 * The answers only start the right flow; free-ticket eligibility is always decided by the server after verification.
 */
export default function AccessRegister() {
  const router = useRouter();
  const { next } = useLocalSearchParams<{ next?: string }>();
  const { a } = useAccessT();
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [email, setEmail] = useState('');
  const [dob, setDob] = useState('');
  const [password, setPassword] = useState('');
  const [gender, setGender] = useState<'MALE' | 'FEMALE' | null>(null);
  const [answer, setAnswer] = useState<'YES' | 'NO' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const mobile = normalizeIndianMobile(phone);
    const isoDob = parseDob(dob);
    if (!isValidName(name)) return setError(a('errName'));
    if (!mobile) return setError(a('errMobile'));
    if (!isValidEmail(email)) return setError(a('errEmail'));
    if (!isoDob) return setError(a('errDob'));
    if (password.length < 8 || !/[A-Za-z]/.test(password) || !/\d/.test(password)) return setError(a('errPassword'));
    if (!gender) return setError(a('errGender'));
    if (!answer) return setError(gender === 'MALE' ? a('errBusPass') : a('errAadhaarAnswer'));
    setError(null);
    setBusy(true);
    try {
      const yes = answer === 'YES';
      const s = await AccessApi.register({
        name: name.trim(), phone: mobile, email: email.trim(), password, gender, date_of_birth: isoDob,
        ...(gender === 'MALE' ? { has_bus_pass: yes } : { has_aadhaar: yes }),
      });
      routeAfterLogin(router, s, typeof next === 'string' ? next : null);
    } catch (e: any) {
      setError(e?.message || a('registrationFailed'));
    } finally {
      setBusy(false);
    }
  };

  const followUp = gender === 'MALE' ? a('busPassQuestion') : gender === 'FEMALE' ? a('aadhaarQuestion') : null;
  const explain =
    gender === 'MALE'
      ? answer === 'YES' ? a('busPassYesNote') : answer === 'NO' ? a('busPassNoNote') : null
      : gender === 'FEMALE'
        ? answer === 'YES' ? a('aadhaarYesNote') : answer === 'NO' ? a('aadhaarNoNote') : null
        : null;

  return (
    <AuthScreen
      title={a('registerTitle')}
      subtitle={a('registerSub')}
      footer={<AuthButton label={a('createAccount')} icon="person-add-outline" onPress={submit} loading={busy} />}
    >
      <Text style={accessStyles.muted}>{a('whoAreYou')}</Text>
      <Choice
        options={[{ value: 'MALE', label: a('male') }, { value: 'FEMALE', label: a('female') }]}
        value={gender}
        onChange={v => { setGender(v as any); setAnswer(null); }}
      />
      {followUp ? (
        <>
          <Text style={accessStyles.muted}>{followUp}</Text>
          <Choice options={[{ value: 'YES', label: a('yes') }, { value: 'NO', label: a('no') }]} value={answer} onChange={v => setAnswer(v as any)} />
        </>
      ) : null}
      {explain ? <Notice tone="info" body={explain} /> : null}
      <Field label={a('fullName')} value={name} onChangeText={setName} autoCapitalize="words" />
      <Field label={a('mobile')} value={phone} onChangeText={setPhone} keyboardType="phone-pad" placeholder="98450 12345" />
      <Field label={a('email')} value={email} onChangeText={setEmail} keyboardType="email-address" />
      <Field label={a('dobLabel')} value={dob} onChangeText={setDob} placeholder="DD-MM-YYYY" keyboardType="numbers-and-punctuation" />
      <Field label={a('password')} value={password} onChangeText={setPassword} secure />
      <Text style={[accessStyles.muted, { marginBottom: 12 }]}>{a('genderNote')}</Text>
      <ErrorText text={error} />
      <AuthButton variant="link" label={a('alreadyRegistered')} onPress={() => router.replace('/access' as any)} />
    </AuthScreen>
  );
}
